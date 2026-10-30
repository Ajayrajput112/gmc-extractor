"""
test_validate.py - Unit tests for validation rules and grounding checks.
"""

from datetime import datetime
from src.schema import (
    GMCPolicyExtraction,
    PolicyDetails,
    DemographicsDetails,
    FeatureBenefit,
    FeatureStatus
)
from src.validate import (
    parse_date_string,
    check_evidence_in_text,
    validate_extraction,
    build_reprompt_message
)


def test_parse_date_string():
    """Verify parsing of multiple standard date formats."""
    d1 = parse_date_string("15-Jan-2024")
    assert d1 == datetime(2024, 1, 15)

    d2 = parse_date_string("01-August-2023")
    assert d2 == datetime(2023, 8, 1)

    d3 = parse_date_string("02/06/2022")
    assert d3 == datetime(2022, 6, 2)

    d4 = parse_date_string("2024-04-26")
    assert d4 == datetime(2024, 4, 26)

    d5 = parse_date_string("Midnight 31-Dec-2024")
    assert d5 == datetime(2024, 12, 31)


def test_check_evidence_in_text_exact_and_normalized():
    """Verify evidence substring matching."""
    text = "Room rent maximum eligibility for Normal Hospitalization 2% of Sum Insured per day."

    # Exact
    assert check_evidence_in_text("2% of Sum Insured per day", text) is True

    # Whitespace normalized
    assert check_evidence_in_text("2 %  of   Sum Insured\nper day", text) is True

    # Non-existent
    assert check_evidence_in_text("No limit on room rent whatsoever", text) is False


def test_validate_dates_span_one_year():
    """Verify that a 364/365 day policy passes date validation, while 180 days fails."""
    # 365 days: 15-Jan-2024 to 14-Jan-2025
    ext_pass = GMCPolicyExtraction(
        policy_details=PolicyDetails(
            start_date="15-Jan-2024",
            end_date="14-Jan-2025"
        )
    )
    report_pass = validate_extraction(ext_pass, {1: "page 1 text 15-Jan-2024 14-Jan-2025"})
    assert not any(i.issue_type == "DATE_SPAN" for i in report_pass.issues)

    # 180 days: 15-Jan-2024 to 15-Jul-2024
    ext_fail = GMCPolicyExtraction(
        policy_details=PolicyDetails(
            start_date="15-Jan-2024",
            end_date="15-Jul-2024"
        )
    )
    report_fail = validate_extraction(ext_fail, {1: "page 1 text 15-Jan-2024 15-Jul-2024"})
    assert any(i.issue_type == "DATE_SPAN" for i in report_fail.issues)


def test_validate_demographics_math():
    """Verify that lives matching sum of members passes, and mismatch triggers issue."""
    # Pass: 100 + 50 = 150
    ext_pass = GMCPolicyExtraction(
        demographics=DemographicsDetails(
            total_employees=100,
            total_dependents=50,
            total_lives=150
        )
    )
    report_pass = validate_extraction(ext_pass, {1: "page text 100 150"})
    assert not any(i.issue_type == "DEMOGRAPHICS_MATH" for i in report_pass.issues)

    # Mismatch: 100 + 50 != 200
    ext_fail = GMCPolicyExtraction(
        demographics=DemographicsDetails(
            total_employees=100,
            total_dependents=50,
            total_lives=200
        )
    )
    report_fail = validate_extraction(ext_fail, {1: "page text 100 200"})
    assert any(i.issue_type == "DEMOGRAPHICS_MATH" for i in report_fail.issues)


def test_validate_evidence_grounding():
    """Verify that evidence quotes present in page pass, while hallucinated quotes fail."""
    pages = {
        1: "Header policy info",
        2: "Room Rent: Maximum eligibility for Normal Hospitalization 2% of Sum Insured per day."
    }

    ext = GMCPolicyExtraction()
    ext.features.room_rent = FeatureBenefit(
        status=FeatureStatus.COVERED,
        limit_percent_si=2.0,
        source_page=2,
        evidence="Maximum eligibility for Normal Hospitalization 2% of Sum Insured per day"
    )
    ext.features.maternity_normal = FeatureBenefit(
        status=FeatureStatus.COVERED,
        limit_amount=50000.0,
        source_page=2,
        evidence="Normal delivery covered up to 50000 INR completely free"  # Hallucinated quote
    )

    report = validate_extraction(ext, pages)
    # room_rent should be grounded
    assert not any(i.field_path == "features.room_rent" for i in report.issues)
    # maternity_normal should fail grounding
    ungrounded = [i for i in report.issues if i.field_path == "features.maternity_normal"]
    assert len(ungrounded) == 1
    assert ungrounded[0].issue_type == "EVIDENCE_UNGROUNDED"


def test_validate_header_grounding():
    """Verify that header dates, premium, and lives ground against document text."""
    pages = {
        1: (
            "Policy Schedule No: POL-TEST-12345\n"
            "Period: 15-Jan-2024 to 14-Jan-2025\n"
            "Net Premium: Rs. 1,75,000.00\n"
            "Total Gross Premium: Rs. 1,95,000.00\n"
            "Total Insured Lives: 75 (Employees: 50, Dependents: 25)"
        )
    }

    from src.schema import PremiumDetails

    # Grounded extraction
    ext_pass = GMCPolicyExtraction(
        policy_details=PolicyDetails(
            policy_number="POL-TEST-12345",
            start_date="15-Jan-2024",
            end_date="14-Jan-2025"
        ),
        premium=PremiumDetails(
            net_premium=175000.0,
            total_premium=195000.0
        ),
        demographics=DemographicsDetails(
            total_employees=50,
            total_dependents=25,
            total_lives=75
        )
    )
    report_pass = validate_extraction(ext_pass, pages)
    assert not any(i.issue_type == "HEADER_UNGROUNDED" for i in report_pass.issues)

    # Hallucinated premium extraction
    ext_fail = GMCPolicyExtraction(
        policy_details=PolicyDetails(
            policy_number="POL-TEST-12345",
            start_date="15-Jan-2024",
            end_date="14-Jan-2025"
        ),
        premium=PremiumDetails(
            net_premium=9999999.0,  # Hallucinated number not in text
            total_premium=195000.0
        ),
        demographics=DemographicsDetails(
            total_employees=50,
            total_dependents=25,
            total_lives=75
        )
    )
    report_fail = validate_extraction(ext_fail, pages)
    ungrounded = [i for i in report_fail.issues if i.issue_type == "HEADER_UNGROUNDED"]
    assert len(ungrounded) == 1
    assert ungrounded[0].field_path == "premium.net_premium"


def test_build_reprompt_message():
    """Verify that build_reprompt_message constructs targeted prompt with failed fields."""
    pages = {1: "Page 1 content", 2: "Page 2 content"}
    ext = GMCPolicyExtraction()
    ext.features.room_rent = FeatureBenefit(
        status=FeatureStatus.COVERED,
        source_page=2,
        evidence="Non-existent quote"
    )
    report = validate_extraction(ext, pages)
    reprompt = build_reprompt_message(report, pages)

    assert "FAILED VALIDATION ISSUES:" in reprompt
    assert "features.room_rent" in reprompt
    assert "--- PAGE 2 ---" in reprompt

