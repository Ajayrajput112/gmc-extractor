"""
validate.py - Rule-based validation rules and targeted LLM re-prompting.

Rules enforced:
1. Policy tenure: Start and end dates must span approximately 1 year (~350 to 370 days).
2. Sum Insured tiers: Must be positive numeric values.
3. Demographics arithmetic: Total lives must equal sum of employees + dependents (or individual member breakdown).
4. Evidence Grounding: Every cited evidence quote must appear verbatim in the source document page text.
5. Targeted re-prompting: Re-prompts the LLM specifically for failing fields rather than regenerating the entire extraction.
"""

from datetime import datetime
import re
from typing import Dict, List, Optional, Tuple, Any
from pydantic import BaseModel, Field

from src.schema import GMCPolicyExtraction, FeatureBenefit, FeatureStatus


class ValidationIssue(BaseModel):
    """Represents a specific validation finding."""
    field_path: str
    issue_type: str  # 'DATE_SPAN', 'SI_TIER', 'DEMOGRAPHICS_MATH', 'EVIDENCE_UNGROUNDED', 'PAGE_OUT_OF_BOUNDS'
    message: str
    page_number: Optional[int] = None
    evidence: Optional[str] = None


class ValidationReport(BaseModel):
    """Summary report of all validation checks."""
    is_valid: bool
    status: str  # 'PASSED', 'PASSED_WITH_WARNINGS', 'FAILED'
    issues: List[ValidationIssue] = Field(default_factory=list)
    messages: List[str] = Field(default_factory=list)


def parse_date_string(date_str: Optional[str]) -> Optional[datetime]:
    """
    Attempts to parse date strings in various standard Indian insurance formats:
    - 15-Jan-2024, 17-Mar-2022, 01-August-2023
    - 02/04/2022, 17/03/2022, 01/08/2023
    - 2022-04-02, 2023-08-01
    - 26 April 2024
    """
    if not date_str:
        return None

    # Clean string: remove time portions like "00:00 hrs", "Midnight", etc.
    cleaned = re.sub(r"\b(00:00|23:59|hrs|hours|midnight|noon)\b", "", str(date_str), flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", cleaned)

    formats = [
        "%d-%b-%Y",      # 15-Jan-2024
        "%d-%B-%Y",      # 01-August-2023
        "%d/%m/%Y",      # 02/04/2022
        "%d-%m-%Y",      # 02-04-2022
        "%Y-%m-%d",      # 2022-04-02
        "%d %B %Y",      # 26 April 2024
        "%d %b %Y",      # 26 Apr 2024
        "%B %d, %Y",     # April 26, 2024
        "%b %d, %Y",     # Apr 26, 2024
        "%d.%m.%Y",      # 02.04.2022
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    # Try extracting via regex DD-Mon-YYYY or DD/MM/YYYY
    match_dmy = re.search(r"(\d{1,2})[-/](\w{3,9})[-/](\d{4})", cleaned)
    if match_dmy:
        d, m, y = match_dmy.groups()
        for f in ["%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y"]:
            try:
                return datetime.strptime(f"{d}-{m}-{y}", f)
            except ValueError:
                pass

    return None


def normalize_text_for_matching(text: str) -> str:
    """Normalizes text for substring search by removing extra whitespace and punctuation."""
    if not text:
        return ""
    t = text.lower()
    # Replace non-alphanumeric characters (symbols, punctuation) with space
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse all whitespace sequences into a single space
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def check_evidence_in_text(evidence: str, target_text: str) -> bool:
    """
    Checks if evidence quote appears in the target text.
    Uses exact substring match first, then whitespace/punctuation-normalized matching.
    """
    if not evidence or not target_text:
        return False

    # 1. Exact match
    if evidence.strip() in target_text:
        return True

    # 2. Normalized match
    norm_evidence = normalize_text_for_matching(evidence)
    norm_target = normalize_text_for_matching(target_text)

    if norm_evidence and norm_evidence in norm_target:
        return True

    # 3. Sub-phrase match if evidence is long (> 30 chars), check if 80% prefix is present
    if len(norm_evidence) > 30:
        prefix = norm_evidence[:int(len(norm_evidence) * 0.8)]
        if prefix in norm_target:
            return True

    return False


def check_number_grounded(val: Optional[float], text: str) -> bool:
    """
    Checks if a numeric value (e.g. premium, lives) appears in the text,
    accounting for comma formatting (e.g. 150,000 vs 150000).
    """
    if val is None or val == 0:
        return True
    s_val = str(int(val)) if isinstance(val, (int, float)) and val == int(val) else str(val)
    patterns = [s_val, f"{int(val):,}"] if isinstance(val, (int, float)) else [s_val]
    for p in patterns:
        if p in text or p.replace(",", "") in text.replace(",", ""):
            return True
    return False


def check_date_grounded(date_str: Optional[str], text: str) -> bool:
    """
    Checks if an extracted date appears in the document text.
    Handles verbatim substrings as well as parsed day/month/year tokens.
    """
    if not date_str:
        return True
    if check_evidence_in_text(date_str, text):
        return True
    dt = parse_date_string(date_str)
    if dt:
        day_str = str(dt.day)
        year_str = str(dt.year)
        month_name = dt.strftime("%B").lower()
        month_abbr = dt.strftime("%b").lower()
        text_lower = text.lower()
        if (day_str in text and year_str in text) and (
            month_name in text_lower or month_abbr in text_lower or str(dt.month) in text
        ):
            return True
    return False


def check_string_grounded(val: Optional[str], text: str) -> bool:
    """
    Checks if a string identifier (e.g. policy number) appears in the document text,
    normalizing away dashes, spaces, and slashes if necessary.
    """
    if not val:
        return True
    if val in text:
        return True
    clean_val = re.sub(r"[\s\-_/]", "", val)
    clean_text = re.sub(r"[\s\-_/]", "", text)
    return clean_val.lower() in clean_text.lower()



def validate_extraction(
    extraction: GMCPolicyExtraction,
    pages_text: Dict[int, str]
) -> ValidationReport:
    """
    Performs comprehensive rule-based validation of the extraction:
    1. Dates span ~1 year
    2. SI tiers numeric and positive
    3. Lives arithmetic
    4. Evidence quote grounding
    """
    issues: List[ValidationIssue] = []
    messages: List[str] = []

    # If document is flagged as non-GMC, note and skip medical benefit grounding checks
    if not extraction.is_gmc_policy:
        msg = extraction.flag_notes or f"Non-GMC policy flagged: {extraction.policy_type}."
        messages.append(msg)
        return ValidationReport(
            is_valid=True,
            status="PASSED_WITH_WARNINGS",
            issues=[],
            messages=messages
        )

    # 1. Policy Dates Check
    p_details = extraction.policy_details
    start_dt = parse_date_string(p_details.start_date)
    end_dt = parse_date_string(p_details.end_date)

    if p_details.start_date and p_details.end_date:
        if start_dt and end_dt:
            days = (end_dt - start_dt).days
            # Indian insurance annual policies typically 365 days (or 364/366)
            if not (350 <= days <= 375):
                issue = ValidationIssue(
                    field_path="policy_details.dates",
                    issue_type="DATE_SPAN",
                    message=f"Policy dates span {days} days ({p_details.start_date} to {p_details.end_date}), which deviates from the expected ~1 year (365 days)."
                )
                issues.append(issue)
                messages.append(issue.message)
            else:
                # Store calculated tenure if not set
                if not p_details.policy_tenure_days:
                    p_details.policy_tenure_days = days
        else:
            issue = ValidationIssue(
                field_path="policy_details.dates",
                issue_type="DATE_SPAN",
                message=f"Could not parse policy dates for 1-year verification: start_date='{p_details.start_date}', end_date='{p_details.end_date}'."
            )
            issues.append(issue)
            messages.append(issue.message)

    # 2. Sum Insured Tiers Check
    if p_details.sum_insured_tiers:
        invalid_tiers = [si for si in p_details.sum_insured_tiers if not isinstance(si, (int, float)) or si <= 0]
        if invalid_tiers:
            issue = ValidationIssue(
                field_path="policy_details.sum_insured_tiers",
                issue_type="SI_TIER",
                message=f"Invalid non-positive or non-numeric Sum Insured tiers found: {invalid_tiers}."
            )
            issues.append(issue)
            messages.append(issue.message)

    # 3. Demographics Arithmetic Check
    demo = extraction.demographics
    if demo.total_lives is not None:
        # Check against employees + dependents
        if demo.total_employees is not None and demo.total_dependents is not None:
            expected_lives = demo.total_employees + demo.total_dependents
            if demo.total_lives != expected_lives:
                issue = ValidationIssue(
                    field_path="demographics.total_lives",
                    issue_type="DEMOGRAPHICS_MATH",
                    message=f"Demographics mismatch: total_lives ({demo.total_lives}) != total_employees ({demo.total_employees}) + total_dependents ({demo.total_dependents}) = {expected_lives}."
                )
                issues.append(issue)
                messages.append(issue.message)
        # Check against individual member breakdown if dependents is None but breakdown exists
        elif demo.total_employees is not None:
            subparts = [p for p in [demo.total_spouses, demo.total_children, demo.total_parents] if p is not None]
            if subparts:
                expected_lives = demo.total_employees + sum(subparts)
                if demo.total_lives != expected_lives:
                    issue = ValidationIssue(
                        field_path="demographics.total_lives",
                        issue_type="DEMOGRAPHICS_MATH",
                        message=f"Demographics mismatch: total_lives ({demo.total_lives}) != total_employees ({demo.total_employees}) + breakdown sum ({sum(subparts)}) = {expected_lives}."
                    )
                    issues.append(issue)
                    messages.append(issue.message)

    # 4. Evidence Grounding Verification
    full_doc_text = " ".join(pages_text.values())
    total_pages = len(pages_text)

    features_dict = extraction.features.model_dump()
    for feat_name, feat_val in features_dict.items():
        status = feat_val.get("status")
        evidence = feat_val.get("evidence")
        source_page = feat_val.get("source_page")

        # Only verify evidence for benefits that are not "not_mentioned"
        if status != FeatureStatus.NOT_MENTIONED.value and evidence:
            # Check source page validity
            if source_page is not None:
                if source_page < 1 or source_page > total_pages:
                    issue = ValidationIssue(
                        field_path=f"features.{feat_name}",
                        issue_type="PAGE_OUT_OF_BOUNDS",
                        page_number=source_page,
                        evidence=evidence,
                        message=f"Feature '{feat_name}' cites invalid source_page {source_page} (PDF has {total_pages} pages)."
                    )
                    issues.append(issue)
                    messages.append(issue.message)
                    continue

                page_text = pages_text.get(source_page, "")
                is_on_page = check_evidence_in_text(evidence, page_text)
                if not is_on_page:
                    # Check adjacent pages (+/- 1) before declaring completely ungrounded
                    is_nearby = False
                    for adj in [source_page - 1, source_page + 1]:
                        if adj in pages_text and check_evidence_in_text(evidence, pages_text[adj]):
                            is_nearby = True
                            # Auto-correct page number if found on adjacent page
                            feat_obj = getattr(extraction.features, feat_name, None)
                            if feat_obj:
                                feat_obj.source_page = adj
                            break

                    if not is_nearby:
                        # Check full document
                        is_anywhere = check_evidence_in_text(evidence, full_doc_text)
                        if not is_anywhere:
                            issue = ValidationIssue(
                                field_path=f"features.{feat_name}",
                                issue_type="EVIDENCE_UNGROUNDED",
                                page_number=source_page,
                                evidence=evidence,
                                message=f"Feature '{feat_name}' evidence quote was NOT found in document: \"{evidence[:80]}...\""
                            )
                            issues.append(issue)
                            messages.append(issue.message)

    # 5. Header Fields Grounding Verification (dates, premium, demographics, policy number)
    if extraction.policy_details.policy_number:
        if not check_string_grounded(extraction.policy_details.policy_number, full_doc_text):
            issue = ValidationIssue(
                field_path="policy_details.policy_number",
                issue_type="HEADER_UNGROUNDED",
                evidence=extraction.policy_details.policy_number,
                message=f"Policy number '{extraction.policy_details.policy_number}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    if extraction.policy_details.start_date:
        if not check_date_grounded(extraction.policy_details.start_date, full_doc_text):
            issue = ValidationIssue(
                field_path="policy_details.start_date",
                issue_type="HEADER_UNGROUNDED",
                evidence=extraction.policy_details.start_date,
                message=f"Start date '{extraction.policy_details.start_date}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    if extraction.policy_details.end_date:
        if not check_date_grounded(extraction.policy_details.end_date, full_doc_text):
            issue = ValidationIssue(
                field_path="policy_details.end_date",
                issue_type="HEADER_UNGROUNDED",
                evidence=extraction.policy_details.end_date,
                message=f"End date '{extraction.policy_details.end_date}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    if extraction.premium.net_premium is not None:
        if not check_number_grounded(extraction.premium.net_premium, full_doc_text):
            issue = ValidationIssue(
                field_path="premium.net_premium",
                issue_type="HEADER_UNGROUNDED",
                evidence=str(extraction.premium.net_premium),
                message=f"Net premium '{extraction.premium.net_premium}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    if extraction.premium.total_premium is not None:
        if not check_number_grounded(extraction.premium.total_premium, full_doc_text):
            issue = ValidationIssue(
                field_path="premium.total_premium",
                issue_type="HEADER_UNGROUNDED",
                evidence=str(extraction.premium.total_premium),
                message=f"Total premium '{extraction.premium.total_premium}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    if extraction.demographics.total_lives is not None:
        if not check_number_grounded(extraction.demographics.total_lives, full_doc_text):
            issue = ValidationIssue(
                field_path="demographics.total_lives",
                issue_type="HEADER_UNGROUNDED",
                evidence=str(extraction.demographics.total_lives),
                message=f"Total lives count '{extraction.demographics.total_lives}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    if extraction.demographics.total_employees is not None:
        if not check_number_grounded(extraction.demographics.total_employees, full_doc_text):
            issue = ValidationIssue(
                field_path="demographics.total_employees",
                issue_type="HEADER_UNGROUNDED",
                evidence=str(extraction.demographics.total_employees),
                message=f"Total employees count '{extraction.demographics.total_employees}' was not found in document text."
            )
            issues.append(issue)
            messages.append(issue.message)

    # Determine status
    if not issues:
        status = "PASSED"
        messages.append("All policy validation checks passed successfully.")
    else:
        # Check if any ungrounded evidence or header issues exist
        has_critical = any(i.issue_type in ("EVIDENCE_UNGROUNDED", "HEADER_UNGROUNDED") for i in issues)
        status = "FAILED" if has_critical else "PASSED_WITH_WARNINGS"

    return ValidationReport(
        is_valid=(status == "PASSED"),
        status=status,
        issues=issues,
        messages=messages
    )


class TargetedFieldCorrection(BaseModel):
    """Container for re-prompting corrections of failed fields."""
    corrected_features: Dict[str, FeatureBenefit] = Field(
        default_factory=dict,
        description="Map of feature_name to corrected FeatureBenefit"
    )
    corrected_start_date: Optional[str] = Field(default=None)
    corrected_end_date: Optional[str] = Field(default=None)
    corrected_total_lives: Optional[int] = Field(default=None)


def build_reprompt_message(
    report: ValidationReport,
    pages_text: Dict[int, str]
) -> str:
    """
    Constructs a targeted prompt containing only the failed fields and the relevant page context.
    """
    prompt_lines = [
        "You are an expert insurance document auditor. Some fields extracted in a previous pass failed rule-based validation.",
        "Your task is to review the specific failed fields below against the exact source document text and correct them.",
        "",
        "RULES:",
        "1. If a quote was not found or the benefit is not actually mentioned, set status='not_mentioned' and all limits/evidence to null.",
        "2. Evidence quotes MUST be copied verbatim from the document text.",
        "3. Do NOT guess or hallucinate any numbers or benefits.",
        "",
        "FAILED VALIDATION ISSUES:"
    ]

    relevant_pages = set()
    for issue in report.issues:
        prompt_lines.append(f"- [{issue.issue_type}] Field: {issue.field_path}: {issue.message}")
        if issue.page_number and issue.page_number in pages_text:
            relevant_pages.add(issue.page_number)

    # Add page 1 and 2 by default for dates/demographics
    relevant_pages.add(1)
    if len(pages_text) >= 2:
        relevant_pages.add(2)

    prompt_lines.append("\nRELEVANT DOCUMENT TEXT EXCERPTS:")
    for p_num in sorted(relevant_pages):
        prompt_lines.append(f"--- PAGE {p_num} ---")
        prompt_lines.append(pages_text[p_num][:3000])  # Cap per page to avoid context blowout
        prompt_lines.append(f"--- END PAGE {p_num} ---\n")

    return "\n".join(prompt_lines)
