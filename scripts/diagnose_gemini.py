"""
diagnose_gemini.py - Diagnostic test suite for Gemini API connectivity and schema limits.
Runs progressive test steps (A to F) to pinpoint the exact failure point of live Gemini API calls.

Steps:
  a. Trivial prompt, no config
  b. response_mime_type="application/json" only, no schema
  c. Tiny Pydantic schema (3 fields) as response_schema
  d. Full GMCPolicyExtraction schema with a short dummy prompt
  e. Full request exactly as llm.py builds it, with real prompt, system instruction, and sample PDF text
  f. Plan B: response_mime_type="application/json" with in-prompt schema + Pydantic validation (No response_schema)
"""

import argparse
import json
import os
import random
import sys
import time
from typing import Any, Dict, Optional, Tuple

sys.stdout.reconfigure(line_buffering=True)
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google import genai
from google.genai import types
from google.genai.errors import ClientError, APIError, ServerError

from src.schema import GMCPolicyExtraction
from src.extractor import extract_pdf_content
from src.classifier import PolicyClassifier
from src.llm import SYSTEM_INSTRUCTION, build_extraction_prompt, clean_json_text

load_dotenv()


def calculate_schema_metrics(schema_dict: Dict[str, Any]) -> Tuple[int, int, int]:
    """
    Calculates (character_count, total_properties_count, max_nesting_depth)
    for a given JSON schema dictionary.
    """
    json_str = json.dumps(schema_dict)
    char_count = len(json_str)

    def count_properties(obj: Any) -> int:
        count = 0
        if isinstance(obj, dict):
            if "properties" in obj and isinstance(obj["properties"], dict):
                count += len(obj["properties"])
            for v in obj.values():
                count += count_properties(v)
        elif isinstance(obj, list):
            for item in obj:
                count += count_properties(item)
        return count

    def get_max_depth(obj: Any, current_depth: int = 1) -> int:
        if not isinstance(obj, (dict, list)):
            return current_depth
        max_d = current_depth
        if isinstance(obj, dict):
            for v in obj.values():
                max_d = max(max_d, get_max_depth(v, current_depth + 1))
        elif isinstance(obj, list):
            for item in obj:
                max_d = max(max_d, get_max_depth(item, current_depth + 1))
        return max_d

    total_props = count_properties(schema_dict)
    depth = get_max_depth(schema_dict)
    return char_count, total_props, depth


def format_error(e: Exception) -> str:
    """Formats full error details including status code, message, and response body."""
    lines = [f"Exception Type: {type(e).__name__}", f"Error Message: {str(e)}"]

    for attr in ["code", "status_code", "status"]:
        if hasattr(e, attr) and getattr(e, attr) is not None:
            lines.append(f"HTTP Status:    {getattr(e, attr)}")
            break

    if hasattr(e, "response_json") and getattr(e, "response_json"):
        lines.append(f"Response JSON:  {json.dumps(getattr(e, 'response_json'), indent=2)}")
    elif hasattr(e, "details") and getattr(e, "details"):
        lines.append(f"Details JSON:   {json.dumps(getattr(e, 'details'), indent=2)}")

    if hasattr(e, "response") and getattr(e, "response") is not None:
        resp = getattr(e, "response")
        if hasattr(resp, "text") and resp.text:
            lines.append(f"Response Text:  {resp.text}")
        elif hasattr(resp, "body") and resp.body:
            lines.append(f"Response Body:  {resp.body}")

    return "\n".join(lines)


def call_with_transient_retry(
    client: genai.Client,
    model_name: str,
    contents: Any,
    config: Optional[types.GenerateContentConfig] = None,
    max_retries: int = 3,
    base_delay: float = 2.0
) -> types.GenerateContentResponse:
    """Calls generate_content with backoff retry specifically for 503 and 429."""
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
            is_transient = (
                code in (429, 503)
                or "503" in msg
                or "429" in msg
                or "UNAVAILABLE" in status
                or "RESOURCE_EXHAUSTED" in status
                or "high demand" in msg.lower()
            )
            if is_transient and attempt < max_retries:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0.5, 1.5), 20.0)
                print(f"    [Transient {code or status} error, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})...]", flush=True)
                time.sleep(delay)
                continue
            raise e


# -------------------------------------------------------------
# Tiny Schema for Test Step C
# -------------------------------------------------------------
class TinyDiagnosticSchema(BaseModel):
    """Minimal 3-field Pydantic schema."""
    status: str = Field(description="Operational status")
    count: int = Field(description="Numeric count")
    is_valid: bool = Field(description="Boolean indicator")


def run_diagnostics(target_model: Optional[str] = None):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model_name = target_model or os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

    print("=" * 70, flush=True)
    print("GEMINI API DIAGNOSTIC SUITE", flush=True)
    print("=" * 70, flush=True)
    print(f"Target Model:  {model_name}", flush=True)
    print(f"API Key Set:   {'YES (' + api_key[:4] + '...' + api_key[-4:] + ')' if api_key else 'NO (MISSING!)'}", flush=True)
    print("=" * 70, flush=True)

    if not api_key:
        print("\n[CRITICAL ERROR] GEMINI_API_KEY is not set. Please set it in your .env file.", flush=True)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    results = {}

    # -----------------------------------------------------------------
    # Step A: Trivial prompt, no config
    # -----------------------------------------------------------------
    print("\n[Step A] Trivial Prompt (No Config)...", flush=True)
    try:
        res_a = call_with_transient_retry(
            client=client,
            model_name=model_name,
            contents="Reply with the single word OK."
        )
        print("  -> Status: PASS", flush=True)
        print(f"  -> Model Reply: {res_a.text.strip() if res_a.text else '<empty>'}", flush=True)
        results["Step A (Trivial prompt, no config)"] = "PASS"
    except Exception as e:
        print("  -> Status: FAIL", flush=True)
        print("  -> Full Error Body:", flush=True)
        print(format_error(e), flush=True)
        results["Step A (Trivial prompt, no config)"] = "FAIL"

    # -----------------------------------------------------------------
    # Step B: response_mime_type="application/json" only, no schema
    # -----------------------------------------------------------------
    print("\n[Step B] JSON Mode Only (No Schema)...", flush=True)
    try:
        cfg_b = types.GenerateContentConfig(
            response_mime_type="application/json"
        )
        res_b = call_with_transient_retry(
            client=client,
            model_name=model_name,
            contents="Return a JSON object with key 'status' equal to 'OK'.",
            config=cfg_b
        )
        print("  -> Status: PASS", flush=True)
        print(f"  -> Model Reply: {res_b.text.strip() if res_b.text else '<empty>'}", flush=True)
        results["Step B (JSON mode only, no schema)"] = "PASS"
    except Exception as e:
        print("  -> Status: FAIL", flush=True)
        print("  -> Full Error Body:", flush=True)
        print(format_error(e), flush=True)
        results["Step B (JSON mode only, no schema)"] = "FAIL"

    # -----------------------------------------------------------------
    # Step C: Tiny Pydantic schema (3 fields) as response_schema
    # -----------------------------------------------------------------
    print("\n[Step C] Tiny Pydantic Schema (3 fields as response_schema)...", flush=True)
    tiny_schema_dict = TinyDiagnosticSchema.model_json_schema()
    chars_c, props_c, depth_c = calculate_schema_metrics(tiny_schema_dict)
    print(f"  -> Schema Metrics: {chars_c} chars | {props_c} properties | depth {depth_c}", flush=True)
    try:
        cfg_c = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TinyDiagnosticSchema
        )
        res_c = call_with_transient_retry(
            client=client,
            model_name=model_name,
            contents="Return status='OK', count=1, is_valid=true.",
            config=cfg_c
        )
        print("  -> Status: PASS", flush=True)
        print(f"  -> Model Reply: {res_c.text.strip() if res_c.text else '<empty>'}", flush=True)
        results["Step C (Tiny 3-field response_schema)"] = "PASS"
    except Exception as e:
        print("  -> Status: FAIL", flush=True)
        print("  -> Full Error Body:", flush=True)
        print(format_error(e), flush=True)
        results["Step C (Tiny 3-field response_schema)"] = "FAIL"

    # -----------------------------------------------------------------
    # Step D: Full GMCPolicyExtraction schema with a short dummy prompt
    # -----------------------------------------------------------------
    print("\n[Step D] Full GMCPolicyExtraction Schema with Short Dummy Prompt...", flush=True)
    full_schema_dict = GMCPolicyExtraction.model_json_schema()
    chars_d, props_d, depth_d = calculate_schema_metrics(full_schema_dict)
    print(f"  -> Schema Metrics: {chars_d} chars | {props_d} properties | depth {depth_d}", flush=True)
    try:
        cfg_d = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GMCPolicyExtraction
        )
        res_d = call_with_transient_retry(
            client=client,
            model_name=model_name,
            contents="Extract dummy policy: Policy No POL-999, status covered.",
            config=cfg_d
        )
        print("  -> Status: PASS", flush=True)
        print(f"  -> Model Reply (preview): {res_d.text[:120] if res_d.text else '<empty>'}...", flush=True)
        results["Step D (Full GMCPolicyExtraction response_schema)"] = "PASS"
    except Exception as e:
        print("  -> Status: FAIL", flush=True)
        print("  -> Full Error Body:", flush=True)
        print(format_error(e), flush=True)
        results["Step D (Full GMCPolicyExtraction response_schema)"] = "FAIL"

    # -----------------------------------------------------------------
    # Step E: Full request exactly as llm.py builds it, with real PDF text
    # -----------------------------------------------------------------
    print("\n[Step E] Full Pipeline Request (System Instruction + Real PDF Prompt + response_schema=GMCPolicyExtraction)...", flush=True)
    sample_pdf = "samples/olj4KTUo9B1546-1692687606_925469 - 00 GMC Renewal Policy 00.pdf"
    if not os.path.exists(sample_pdf):
        all_pdfs = [os.path.join("samples", f) for f in os.listdir("samples") if f.endswith(".pdf")]
        sample_pdf = all_pdfs[0] if all_pdfs else None

    if not sample_pdf:
        print("  -> Status: SKIPPED (No sample PDF found in samples/)", flush=True)
        results["Step E (Full request with sample PDF)"] = "SKIPPED"
    else:
        print(f"  -> Using Sample Document: {os.path.basename(sample_pdf)}", flush=True)
        ext_res = extract_pdf_content(sample_pdf)
        classifier = PolicyClassifier()
        p1_text = ext_res.pages_text.get(1, "")
        hint = classifier.analyze(p1_text)
        prompt = build_extraction_prompt(ext_res.full_text, hint, os.path.basename(sample_pdf))

        try:
            cfg_e = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=GMCPolicyExtraction,
                temperature=0.0
            )

            res_e = call_with_transient_retry(
                client=client,
                model_name=model_name,
                contents=prompt,
                config=cfg_e
            )
            print("  -> Status: PASS", flush=True)
            print(f"  -> Model Reply (preview): {res_e.text[:150] if res_e.text else '<empty>'}...", flush=True)
            results["Step E (Full request with sample PDF)"] = "PASS"
        except Exception as e:
            print("  -> Status: FAIL", flush=True)
            print("  -> Full Error Body:", flush=True)
            print(format_error(e), flush=True)
            results["Step E (Full request with sample PDF)"] = "FAIL"

    # -----------------------------------------------------------------
    # Step F: Plan B (JSON Mode + In-Prompt Schema + Pydantic Validation)
    # -----------------------------------------------------------------
    print("\n[Step F] Plan B: Pure JSON Mode (No response_schema) + Pydantic Validation on Real PDF...", flush=True)
    if not sample_pdf:
        print("  -> Status: SKIPPED (No sample PDF found in samples/)", flush=True)
        results["Step F (Plan B JSON Mode + Pydantic Validation)"] = "SKIPPED"
    else:
        try:
            cfg_f = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.0
            )
            res_f = call_with_transient_retry(
                client=client,
                model_name=model_name,
                contents=prompt,
                config=cfg_f
            )
            cleaned = clean_json_text(res_f.text if res_f.text else "{}")
            parsed = GMCPolicyExtraction.model_validate_json(cleaned)
            print("  -> Status: PASS (Successfully parsed and validated into GMCPolicyExtraction Pydantic model!)", flush=True)
            print(f"  -> Insurer: {parsed.insurer_name} | Policy No: {parsed.policy_details.policy_number}", flush=True)
            print(f"  -> Features with values: {sum(1 for f in parsed.features.model_dump().values() if f.get('status') != 'not_mentioned')}/30", flush=True)
            results["Step F (Plan B JSON Mode + Pydantic Validation)"] = "PASS"
        except Exception as e:
            print("  -> Status: FAIL", flush=True)
            print("  -> Full Error Body:", flush=True)
            print(format_error(e), flush=True)
            results["Step F (Plan B JSON Mode + Pydantic Validation)"] = "FAIL"

    # -----------------------------------------------------------------
    # Diagnostic Summary Table
    # -----------------------------------------------------------------
    print("\n" + "=" * 70, flush=True)
    print("DIAGNOSTIC SUMMARY TABLE", flush=True)
    print("=" * 70, flush=True)
    for step_name, status in results.items():
        print(f"  {step_name:<55} [ {status} ]", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini API Diagnostic Suite")
    parser.add_argument("--model", type=str, default=None, help="Gemini model name to test (e.g. gemini-3.7-flash)")
    args = parser.parse_args()
    run_diagnostics(target_model=args.model)
