"""
test_mock_integration.py - Integration test for extract_gmc_policy_data with mocked Gemini client.
"""

from unittest.mock import MagicMock
from src.schema import (
    GMCPolicyExtraction,
    PolicyDetails,
    PremiumDetails,
    DemographicsDetails,
    FeatureBenefit,
    FeatureStatus
)
from src.classifier import PolicyClassifier
from src.llm import extract_gmc_policy_data


def test_extract_gmc_policy_data_mocked_llm():
    """Verify that extract_gmc_policy_data processes mocked structured Gemini response."""
    # Build mock response
    mock_extraction = GMCPolicyExtraction(
        is_gmc_policy=True,
        policy_type="Group Medical Cover",
        insurer_name="Care Health Insurance Limited",
        tpa_name="In-House / Direct Insurer Claims Team",
        policy_details=PolicyDetails(
            policy_number="POL-MOCK-998877",
            policy_holder_name="Acme Corp Solutions",
            start_date="15-Jan-2024",
            end_date="14-Jan-2025",
            sum_insured_tiers=[250000.0, 500000.0]
        ),
        premium=PremiumDetails(
            net_premium=120000.0,
            gst_amount=21600.0,
            total_premium=141600.0,
            payment_frequency="ANNUAL PREMIUM"
        ),
        demographics=DemographicsDetails(
            total_employees=80,
            total_dependents=40,
            total_lives=120
        )
    )
    mock_extraction.features.room_rent = FeatureBenefit(
        status=FeatureStatus.COVERED,
        limit_percent_si=2.0,
        source_page=2,
        evidence="2 % of Sum Insured per day"
    )

    mock_response = MagicMock()
    mock_response.parsed = mock_extraction
    mock_response.text = None

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    classifier = PolicyClassifier()
    pages_text = {
        1: (
            "Care Health Insurance Limited Policy No POL-MOCK-998877 Acme Corp Solutions "
            "Start Date 15-Jan-2024 End Date 14-Jan-2025 Net Premium 120000 Total Premium 141600 "
            "Total Lives 120 Total Employees 80"
        ),
        2: "Room Rent: 2 % of Sum Insured per day for Normal Hospitalization"
    }
    hint = classifier.analyze(pages_text[1])

    result = extract_gmc_policy_data(
        full_text="\n\n".join(pages_text.values()),
        pages_text=pages_text,
        total_pages=2,
        filename="test_mock.pdf",
        hint=hint,
        client=mock_client,
        enable_reprompt=False
    )

    assert result.is_gmc_policy is True
    assert result.insurer_name == "Care Health Insurance Limited"
    assert result.features.room_rent.status == FeatureStatus.COVERED
    assert result.features.room_rent.source_page == 2
    assert result.validation_status == "PASSED"
    assert len(result.validation_messages) > 0


def test_extract_gmc_policy_data_plan_b_raw_json():
    """Verify Plan B parses and validates raw JSON text from Gemini without response_schema."""
    json_payload = """
    {
      "is_gmc_policy": true,
      "policy_type": "Group Medical Cover",
      "flag_notes": null,
      "insurer_name": "Star Health and Allied Insurance",
      "tpa_name": "In-House Claims",
      "policy_details": {
        "policy_name": "Medi Classic Group",
        "policy_number": "POL-RAW-12345",
        "policy_holder_name": "Global Tech Services",
        "start_date": "01-Feb-2024",
        "end_date": "31-Jan-2025",
        "policy_tenure_days": 365,
        "is_renewal": false,
        "previous_policy_number": null,
        "family_structure": "Self + Spouse",
        "sum_insured_tiers": [300000.0]
      },
      "premium": {
        "net_premium": 50000.0,
        "gst_amount": 9000.0,
        "total_premium": 59000.0,
        "payment_frequency": "Annual"
      },
      "demographics": {
        "total_employees": 50,
        "total_spouses": 50,
        "total_children": null,
        "total_parents": null,
        "total_dependents": 50,
        "total_lives": 100
      },
      "features": {
        "room_rent": {
          "status": "covered",
          "limit_amount": 5000.0,
          "limit_percent_si": null,
          "days": null,
          "conditions": "Up to Rs 5000 per day",
          "source_page": 1,
          "evidence": "Room rent limit Rs 5000 per day",
          "confidence": 0.95
        }
      }
    }
    """
    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = f"```json\n{json_payload}\n```"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    classifier = PolicyClassifier()
    pages_text = {
        1: "Star Health and Allied Insurance POL-RAW-12345 Global Tech Services Start Date 01-Feb-2024 End Date 31-Jan-2025 Room rent limit Rs 5000 per day Total Lives 100 Total Employees 50"
    }
    hint = classifier.analyze(pages_text[1])

    result = extract_gmc_policy_data(
        full_text=pages_text[1],
        pages_text=pages_text,
        total_pages=1,
        filename="plan_b_sample.pdf",
        hint=hint,
        client=mock_client,
        enable_reprompt=False
    )

    assert result.is_gmc_policy is True
    assert result.insurer_name == "Star Health and Allied Insurance"
    assert result.policy_details.policy_number == "POL-RAW-12345"
    assert result.features.room_rent.status == FeatureStatus.COVERED
    assert result.features.room_rent.limit_amount == 5000.0


def test_extract_gmc_policy_data_plan_b_repair_reprompt():
    """Verify Plan B triggers repair re-prompt when initial JSON is malformed, then parses fixed JSON."""
    invalid_json = '{"is_gmc_policy": "NOT_A_BOOLEAN"}'
    valid_json = """
    {
      "is_gmc_policy": true,
      "policy_type": "Group Medical Cover",
      "insurer_name": "Repaired Health Insurance",
      "policy_details": {
        "policy_number": "POL-REPAIRED-1",
        "start_date": "01-Jan-2024",
        "end_date": "31-Dec-2024"
      },
      "premium": {},
      "demographics": {"total_lives": 50, "total_employees": 50},
      "features": {}
    }
    """

    bad_response = MagicMock()
    bad_response.parsed = None
    bad_response.text = invalid_json

    good_response = MagicMock()
    good_response.parsed = None
    good_response.text = valid_json

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [bad_response, good_response]

    pages_text = {1: "Repaired Health Insurance POL-REPAIRED-1 01-Jan-2024 31-Dec-2024 Total Lives 50 Total Employees 50"}
    classifier = PolicyClassifier()
    hint = classifier.analyze(pages_text[1])

    result = extract_gmc_policy_data(
        full_text=pages_text[1],
        pages_text=pages_text,
        total_pages=1,
        filename="repair_sample.pdf",
        hint=hint,
        client=mock_client,
        enable_reprompt=False
    )

    assert mock_client.models.generate_content.call_count == 2
    assert result.is_gmc_policy is True
    assert result.insurer_name == "Repaired Health Insurance"
    assert result.policy_details.policy_number == "POL-REPAIRED-1"

