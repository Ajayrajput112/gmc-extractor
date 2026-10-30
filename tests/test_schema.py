"""
test_schema.py - Unit tests for Pydantic schema models and enums.
"""

import json
from src.schema import (
    FeatureBenefit,
    FeatureStatus,
    GMCPolicyExtraction,
    PolicyDetails,
    PremiumDetails,
    DemographicsDetails,
    PolicyFeatures
)


def test_feature_benefit_default_shape():
    """Verify that default FeatureBenefit uses status 'not_mentioned' and null fields."""
    fb = FeatureBenefit()
    assert fb.status == FeatureStatus.NOT_MENTIONED
    assert fb.limit_amount is None
    assert fb.limit_percent_si is None
    assert fb.days is None
    assert fb.conditions is None
    assert fb.source_page is None
    assert fb.evidence is None
    assert fb.confidence is None
    assert fb.is_empty() is True


def test_feature_benefit_custom_values():
    """Verify populated FeatureBenefit with limits and evidence."""
    fb = FeatureBenefit(
        status=FeatureStatus.COVERED,
        limit_percent_si=2.0,
        conditions="Normal room rent 2% SI per day",
        source_page=2,
        evidence="Maximum eligibility for Normal Hospitalization 2 % of Sum Insured per day",
        confidence=0.95
    )
    assert fb.status == FeatureStatus.COVERED
    assert fb.limit_percent_si == 2.0
    assert fb.source_page == 2
    assert fb.evidence is not None
    assert fb.is_empty() is False


def test_gmc_policy_extraction_serialization():
    """Verify GMCPolicyExtraction can be serialized to and from JSON cleanly."""
    extraction = GMCPolicyExtraction(
        is_gmc_policy=True,
        policy_type="Group Medical Cover",
        insurer_name="Care Health Insurance Limited",
        tpa_name="In-House / Direct Insurer Claims Team",
        policy_details=PolicyDetails(
            policy_number="POL-TEST-887766",
            policy_holder_name="Acme Health Tech Private Limited",
            start_date="01-Jan-2024",
            end_date="31-Dec-2024",
            sum_insured_tiers=[200000.0, 400000.0]
        ),
        premium=PremiumDetails(
            net_premium=150000.0,
            gst_amount=27000.0,
            total_premium=177000.0,
            payment_frequency="ANNUAL PREMIUM"
        ),
        demographics=DemographicsDetails(
            total_employees=75,
            total_dependents=25,
            total_lives=100
        )
    )
    extraction.features.room_rent = FeatureBenefit(
        status=FeatureStatus.COVERED,
        limit_percent_si=2.0,
        source_page=2,
        evidence="Room Rent 2 % of Sum Insured per day"
    )

    data = extraction.model_dump()
    json_str = json.dumps(data)
    loaded = GMCPolicyExtraction.model_validate_json(json_str)

    assert loaded.is_gmc_policy is True
    assert loaded.insurer_name == "Care Health Insurance Limited"
    assert loaded.policy_details.sum_insured_tiers == [200000.0, 400000.0]
    assert loaded.demographics.total_lives == 100
    assert loaded.features.room_rent.status == FeatureStatus.COVERED
    assert loaded.features.room_rent.limit_percent_si == 2.0


def test_all_28_plus_features_exist():
    """Verify that PolicyFeatures defines all required features from assignment."""
    features = PolicyFeatures()
    required_features = [
        "room_rent", "icu_charges", "pre_hospitalization", "post_hospitalization",
        "maternity_normal", "maternity_c_section", "maternity_waiting_period_9m",
        "baby_day_one_cover", "vaccination_coverage",
        "waiting_period_30_days", "waiting_period_first_second_year", "pre_existing_diseases",
        "day_care_expenses", "opd_benefit", "teleconsultation", "pharmacy_discount",
        "domiciliary_hospitalization", "annual_health_checkup", "modern_treatment",
        "bariatric_treatment", "psychiatric_treatment", "ayush_treatment",
        "lgbtq_live_in_partners", "organ_donor_expenses",
        "infertility_treatment", "surrogacy_treatment",
        "ambulance_charges", "air_ambulance_charges",
        "corporate_buffer", "disease_wise_capping"
    ]
    for feat in required_features:
        assert hasattr(features, feat), f"PolicyFeatures missing expected benefit: {feat}"
        val = getattr(features, feat)
        assert isinstance(val, FeatureBenefit)
