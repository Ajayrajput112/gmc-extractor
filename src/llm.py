"""
llm.py - Gemini LLM integration for structured GMC extraction using google-genai SDK.
Handles prompt construction, synonym mapping, structured JSON generation,
transient retry backoff, full 400 error body reporting, and validation re-prompting.
"""

import json
import os
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv
from pydantic import ValidationError

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError, APIError

from src.schema import (
    GMCPolicyExtraction,
    PolicyDetails,
    PremiumDetails,
    DemographicsDetails,
    PolicyFeatures,
    FeatureBenefit,
    FeatureStatus
)
from src.classifier import ClassificationHint
from src.validate import validate_extraction, build_reprompt_message, TargetedFieldCorrection

load_dotenv()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# Complete list of 30 GMC benefit features defined in the schema
ALL_FEATURE_KEYS = [
    "room_rent",
    "icu_charges",
    "pre_hospitalization",
    "post_hospitalization",
    "maternity_normal",
    "maternity_c_section",
    "maternity_waiting_period_9m",
    "baby_day_one_cover",
    "vaccination_coverage",
    "waiting_period_30_days",
    "waiting_period_first_second_year",
    "pre_existing_diseases",
    "day_care_expenses",
    "opd_benefit",
    "teleconsultation",
    "pharmacy_discount",
    "domiciliary_hospitalization",
    "annual_health_checkup",
    "modern_treatment",
    "bariatric_treatment",
    "psychiatric_treatment",
    "ayush_treatment",
    "lgbtq_live_in_partners",
    "organ_donor_expenses",
    "infertility_treatment",
    "surrogacy_treatment",
    "ambulance_charges",
    "air_ambulance_charges",
    "corporate_buffer",
    "disease_wise_capping"
]


def get_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """Creates a google-genai Client instance."""
    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set it in your .env file or environment variable."
        )
    return genai.Client(api_key=key)


def print_full_error_body(e: Exception) -> None:
    """Prints the comprehensive error body from Gemini API exceptions."""
    print("\n" + "=" * 70, file=sys.stderr, flush=True)
    print(f"[GEMINI API ERROR] {type(e).__name__}:", file=sys.stderr, flush=True)
    code = getattr(e, "code", None)
    status = getattr(e, "status", None)
    msg = getattr(e, "message", str(e))

    if code is not None:
        print(f"  HTTP Code:     {code}", file=sys.stderr, flush=True)
    if status is not None:
        print(f"  Status:        {status}", file=sys.stderr, flush=True)
    print(f"  Message:       {msg}", file=sys.stderr, flush=True)

    if hasattr(e, "response_json") and e.response_json:
        print(f"  Response JSON: {json.dumps(e.response_json, indent=2)}", file=sys.stderr, flush=True)
    elif hasattr(e, "details") and e.details:
        print(f"  Details:       {json.dumps(e.details, indent=2)}", file=sys.stderr, flush=True)

    if hasattr(e, "response") and e.response is not None:
        resp = e.response
        if hasattr(resp, "text") and resp.text:
            print(f"  Response Text: {resp.text}", file=sys.stderr, flush=True)
        elif hasattr(resp, "body") and resp.body:
            print(f"  Response Body: {resp.body}", file=sys.stderr, flush=True)
    print("=" * 70 + "\n", file=sys.stderr, flush=True)


def call_gemini_with_retry(
    client: genai.Client,
    model_name: str,
    contents: Any,
    config: Optional[types.GenerateContentConfig] = None,
    max_retries: int = 4,
    base_delay: float = 2.0
) -> types.GenerateContentResponse:
    """
    Calls generate_content with:
    - Retries and exponential backoff with jitter for 503 (UNAVAILABLE) and 429 (RESOURCE_EXHAUSTED).
    - Verbose full error body printing for 400 (INVALID_ARGUMENT).
    """
    for attempt in range(max_retries + 1):
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
        except Exception as e:
            code = getattr(e, "code", None)
            status = str(getattr(e, "status", ""))
            msg = str(e)

            # Check for 400 ClientError (invalid argument, schema issues)
            if code == 400 or "400" in msg or "INVALID_ARGUMENT" in status:
                print_full_error_body(e)
                raise e

            # Check for transient errors: 503 (service unavailable / high demand) or 429 (rate limits)
            is_transient = (
                code in (429, 503)
                or "503" in msg
                or "429" in msg
                or "UNAVAILABLE" in status
                or "RESOURCE_EXHAUSTED" in status
                or "high demand" in msg.lower()
            )
            if is_transient and attempt < max_retries:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0.5, 1.5), 30.0)
                print(
                    f"    [Transient API error ({code or status}): retrying in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries})...]",
                    flush=True
                )
                time.sleep(delay)
                continue

            print_full_error_body(e)
            raise e


SYSTEM_INSTRUCTION = """You are a senior insurance document intelligence expert specializing in Indian Group Medical Cover (GMC) policy schedules and certificates.
Your objective is to extract structured, 100% faithful policy data and map all benefits into a standardized schema.

STRICT ANTI-HALLUCINATION RULES:
1. NEVER guess, estimate, or assume any value.
2. If a specific benefit, waiting period, condition, or demographic number is NOT explicitly stated in the document text or tables, you MUST set status to 'not_mentioned', and set limit_amount, limit_percent_si, days, conditions, source_page, evidence, and confidence to null.
3. NEVER fabricate evidence quotes. Every 'evidence' string must be an EXACT, VERBATIM substring directly from the document.
4. For every extracted benefit with status != 'not_mentioned', you MUST supply the 1-indexed 'source_page' where it appears.
5. If the document is NOT a Group Medical Cover (GMC) health policy (for example, if it is a Group Personal Accident / GPA policy or Term Life policy), set is_gmc_policy=false, set policy_type accordingly, provide flag_notes, and do NOT force medical benefits (leave all hospitalization/maternity benefits as not_mentioned).

HANDLING INTRA-WORD SPACES & KERNING ARTIFACTS:
- Text extracted from certain PDF engines or font encodings may contain stray spaces within words or numbers (for example: characters in headings, labels, or numbers separated by whitespace).
- Identify words and terms based on context and phonetic spelling regardless of stray spaces, extract the relevant fields, and ensure the 'evidence' quote accurately reflects the text segment from that page.

SYNONYM & CONCEPT RESOLUTION:
- Room Rent: Room Rent capping, Normal Hospitalization room eligibility (percentage of Sum Insured, fixed daily limit, room category, or No Limit).
- ICU Charges: Intensive Care Unit charges, ICCU capping (percentage of Sum Insured, fixed daily limit, or No Limit).
- Pre-Hospitalization: Medical expenses incurred prior to admission. Extract duration in days.
- Post-Hospitalization: Medical expenses incurred following discharge. Extract duration in days.
- Maternity Normal & C-Section: Normal delivery monetary limit and C-Section / LSCS monetary limit. Extract any sub-limits or pre/post-natal expense caps into conditions.
- 9-Month Maternity Waiting Period: Waiver of 9-month waiting period (often 'waived' in group corporate policies).
- Baby Day One Cover: Newborn baby covered from day one of birth.
- Ambulance: Emergency road ambulance charges (monetary limit per hospitalization or per policy period).
- Day Care: Day care treatments or procedures covered without requiring 24-hour hospitalization.
- 30-Day Waiting Period: Initial waiting period (status: 'waived' if waived off, otherwise 'applied' or 'not_covered').
- 1st / 2nd Year Waiting Period: Specific ailments / 1st or 2nd year disease-specific exclusions (status: 'waived' if waived off, otherwise 'applied').
- Pre-Existing Diseases (PED): Pre-existing conditions waiting period (status: 'waived' if waived off, 'covered' if covered from Day 1).
- Corporate Buffer: Corporate floater pool, employer buffer pool limit.
- Demographics: Primary employees / members count, spouse / dependent count, and total lives covered. If dependents count is omitted but total lives and employees are present, compute total_dependents = total_lives - total_employees.
- Sum Insured Tiers: Distinct coverage options / sum insured levels.
"""


def get_json_schema_shape_text() -> str:
    """Returns the JSON schema shape string for in-prompt guidance (Plan B)."""
    feature_template = """      "status": "covered" | "not_covered" | "waived" | "applied" | "not_mentioned",
      "limit_amount": number | null,
      "limit_percent_si": number | null,
      "days": integer | null,
      "conditions": string | null,
      "source_page": integer | null,
      "evidence": string | null,
      "confidence": number | null"""

    features_json = ",\n".join(
        f'    "{key}": {{\n{feature_template}\n    }}'
        for key in ALL_FEATURE_KEYS
    )

    schema_shape = f"""{{
  "is_gmc_policy": boolean,
  "policy_type": "Group Medical Cover" | "Group Personal Accident" | "Group Term Life" | string,
  "flag_notes": string | null,
  "insurer_name": string | null,
  "tpa_name": string | null,
  "policy_details": {{
    "policy_name": string | null,
    "policy_number": string | null,
    "policy_holder_name": string | null,
    "start_date": string | null,
    "end_date": string | null,
    "policy_tenure_days": integer | null,
    "is_renewal": boolean | null,
    "previous_policy_number": string | null,
    "family_structure": string | null,
    "sum_insured_tiers": [number]
  }},
  "premium": {{
    "net_premium": number | null,
    "gst_amount": number | null,
    "total_premium": number | null,
    "payment_frequency": string | null
  }},
  "demographics": {{
    "total_employees": integer | null,
    "total_spouses": integer | null,
    "total_children": integer | null,
    "total_parents": integer | null,
    "total_dependents": integer | null,
    "total_lives": integer | null
  }},
  "features": {{
{features_json}
  }}
}}"""
    return schema_shape


def build_extraction_prompt(
    full_text: str,
    hint: ClassificationHint,
    filename: str
) -> str:
    """Builds the extraction prompt incorporating regex classifier hints and JSON schema shape."""
    hints_text = (
        f"Pre-scan Hints for this document:\n"
        f"- Suggested Insurer: {hint.insurer_hint or 'Not detected by regex - check text'}\n"
        f"- Suggested TPA: {hint.tpa_hint or 'Not detected by regex - check if In-House or external TPA'}\n"
        f"- Preliminary Classification: {hint.policy_type} (is_gmc={hint.is_gmc})\n"
    )
    if hint.flag_notes:
        hints_text += f"- Classification Note: {hint.flag_notes}\n"

    schema_shape = get_json_schema_shape_text()

    prompt = f"""Extract structured insurance data from the policy document below.

Source File: {filename}
{hints_text}

OUTPUT FORMAT SPECIFICATION:
You must return a single valid JSON object strictly matching this schema:
{schema_shape}

INSTRUCTIONS:
1. Verify the insurer name and TPA name from the document text.
2. If this is a Group Personal Accident (GPA) policy, flag is_gmc_policy=False, set policy_type='Group Personal Accident', extract general policy header details, and leave medical features as not_mentioned.
3. For GMC health policies, extract policy details, premium breakdown, demographics (including employees and total lives), and all applicable features.
4. For every covered/waived/applied feature, cite the exact 1-indexed source_page and verbatim evidence quote.
5. If a benefit is absent or not mentioned in the text, set status='not_mentioned' and leave other benefit fields null.
6. Return ONLY the valid JSON object. Do not include markdown code block wrappers (no ```json or ```).

DOCUMENT TEXT (with Page Numbers and Markdown Tables):
{full_text}
"""
    return prompt


def clean_json_text(text: str) -> str:
    """Removes markdown code fences from JSON text if present."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def extract_gmc_policy_data(
    full_text: str,
    pages_text: Dict[int, str],
    total_pages: int,
    filename: str,
    hint: ClassificationHint,
    client: Optional[genai.Client] = None,
    model_name: str = DEFAULT_MODEL,
    enable_reprompt: bool = True,
    use_response_schema: bool = False
) -> GMCPolicyExtraction:
    """
    Main extraction pipeline:
    1. Calls Gemini with pure JSON mode (Plan B) by default, avoiding the 400 INVALID_ARGUMENT
       backend schema size limit that occurs with 300+ properties in response_schema.
    2. Validates JSON response into the GMCPolicyExtraction Pydantic model.
       If validation fails, triggers one repair re-prompt.
    3. Runs rule-based validation on dates, math, and evidence grounding.
    4. Executes targeted re-prompting for failed fields if necessary.
    """
    if client is None:
        client = get_genai_client()

    prompt = build_extraction_prompt(full_text, hint, filename)

    # Determine execution strategy
    # If use_response_schema is explicitly requested, attempt Tier 1; otherwise default to Plan B.
    extraction: Optional[GMCPolicyExtraction] = None

    if use_response_schema:
        try:
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=GMCPolicyExtraction,
                temperature=0.0
            )
            response = call_gemini_with_retry(
                client=client,
                model_name=model_name,
                contents=prompt,
                config=config
            )
            if response.parsed and isinstance(response.parsed, GMCPolicyExtraction):
                extraction = response.parsed
            elif response.text:
                extraction = GMCPolicyExtraction.model_validate_json(clean_json_text(response.text))
        except ClientError as ce:
            print(
                f"[WARNING] Tier 1 response_schema call failed ({ce}). "
                "Falling back to Plan B (Pure JSON Mode + In-Prompt Schema + Pydantic Validation)...",
                file=sys.stderr,
                flush=True
            )
            extraction = None

    # Plan B: Pure JSON mode with in-prompt schema contract and Pydantic validation
    if extraction is None:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.0
        )

        response = call_gemini_with_retry(
            client=client,
            model_name=model_name,
            contents=prompt,
            config=config
        )

        if hasattr(response, "parsed") and isinstance(response.parsed, GMCPolicyExtraction):
            extraction = response.parsed
        else:
            raw_text = clean_json_text(response.text if response.text else "{}")
            try:
                extraction = GMCPolicyExtraction.model_validate_json(raw_text)
            except ValidationError as ve:
                print(
                    f"[WARNING] Initial extraction JSON failed Pydantic validation: {ve}\n"
                    "Triggering Plan B Repair Re-prompt (1 attempt)...",
                    file=sys.stderr,
                    flush=True
                )
                repair_prompt = (
                    f"The following JSON extraction failed schema validation with these errors:\n{str(ve)}\n\n"
                    f"Original JSON produced:\n{raw_text}\n\n"
                    f"Please fix all schema validation issues and return the corrected valid JSON matching "
                    f"the GMCPolicyExtraction schema strictly. Return ONLY the raw JSON object."
                )
                repair_res = call_gemini_with_retry(
                    client=client,
                    model_name=model_name,
                    contents=repair_prompt,
                    config=config
                )
                if hasattr(repair_res, "parsed") and isinstance(repair_res.parsed, GMCPolicyExtraction):
                    extraction = repair_res.parsed
                else:
                    repaired_text = clean_json_text(repair_res.text if repair_res.text else "{}")
                    extraction = GMCPolicyExtraction.model_validate_json(repaired_text)

    # Attach document metadata
    extraction.source_file = filename
    extraction.total_pages = total_pages

    # 2. Run rule-based validation
    report = validate_extraction(extraction, pages_text)
    extraction.validation_status = report.status
    extraction.validation_messages = report.messages

    # 3. Targeted Re-prompting if validation failed on specific fields
    if enable_reprompt and report.status == "FAILED" and report.issues:
        reprompt_text = build_reprompt_message(report, pages_text)
        reprompt_config = types.GenerateContentConfig(
            system_instruction="You are a strict insurance data validator. Correct only the specified failed fields.",
            response_mime_type="application/json",
            temperature=0.0
        )

        try:
            reprompt_res = call_gemini_with_retry(
                client=client,
                model_name=model_name,
                contents=reprompt_text,
                config=reprompt_config
            )

            correction: Optional[TargetedFieldCorrection] = None
            if hasattr(reprompt_res, "parsed") and isinstance(reprompt_res.parsed, TargetedFieldCorrection):
                correction = reprompt_res.parsed
            elif reprompt_res.text:
                corrected_clean = clean_json_text(reprompt_res.text)
                correction = TargetedFieldCorrection.model_validate_json(corrected_clean)

            if correction:
                # Merge corrected features
                for feat_name, feat_val in correction.corrected_features.items():
                    if hasattr(extraction.features, feat_name):
                        setattr(extraction.features, feat_name, feat_val)

                if correction.corrected_start_date:
                    extraction.policy_details.start_date = correction.corrected_start_date
                if correction.corrected_end_date:
                    extraction.policy_details.end_date = correction.corrected_end_date
                if correction.corrected_total_lives is not None:
                    extraction.demographics.total_lives = correction.corrected_total_lives

                # Re-validate after corrections
                updated_report = validate_extraction(extraction, pages_text)
                extraction.validation_status = updated_report.status
                extraction.validation_messages = updated_report.messages
        except Exception as e:
            extraction.validation_messages.append(f"Re-prompting pass encountered an error: {str(e)}")

    return extraction
