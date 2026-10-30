"""
schema.py - Pydantic models for structured GMC insurance extraction.

Every insurance benefit feature uses the unified FeatureBenefit shape:
- status: covered | not_covered | waived | applied | not_mentioned
- limit_amount: monetary limit if stated
- limit_percent_si: percentage of sum insured if stated
- days: number of days if stated (e.g. pre/post hospitalization)
- conditions: free text of conditions/notes
- source_page: page number where found
- evidence: verbatim short quote from text
- confidence: score between 0.0 and 1.0
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class FeatureStatus(str, Enum):
    COVERED = "covered"
    NOT_COVERED = "not_covered"
    WAIVED = "waived"
    APPLIED = "applied"
    NOT_MENTIONED = "not_mentioned"


class FeatureBenefit(BaseModel):
    """
    Unified shape for every benefit/feature extracted from the policy.
    Never guess values: if not explicitly stated, status must be not_mentioned
    and limits/evidence must be null.
    """
    status: FeatureStatus = Field(
        default=FeatureStatus.NOT_MENTIONED,
        description="Coverage status: covered, not_covered, waived, applied, or not_mentioned"
    )
    limit_amount: Optional[float] = Field(
        default=None,
        description="Monetary limit in INR (e.g. 50000.0) if applicable, else null"
    )
    limit_percent_si: Optional[float] = Field(
        default=None,
        description="Limit as a percentage of Sum Insured (e.g. 1.0 for 1%, 2.0 for 2%) if applicable"
    )
    days: Optional[int] = Field(
        default=None,
        description="Number of days (e.g. 30 for pre-hospitalization, 60 for post-hospitalization) if applicable"
    )
    conditions: Optional[str] = Field(
        default=None,
        description="Specific conditions, co-pays, sub-limits, or exclusions stated in the text"
    )
    source_page: Optional[int] = Field(
        default=None,
        description="1-indexed page number in the PDF where this benefit was located"
    )
    evidence: Optional[str] = Field(
        default=None,
        description="Exact verbatim short quote from the source text supporting this extraction"
    )
    confidence: Optional[float] = Field(
        default=None,
        description="Confidence score for this extraction between 0.0 and 1.0"
    )

    def is_empty(self) -> bool:
        return self.status == FeatureStatus.NOT_MENTIONED and self.evidence is None


class PolicyDetails(BaseModel):
    """Core policy header details."""
    policy_name: Optional[str] = Field(default=None, description="Official policy product name, e.g. Group Care 360")
    policy_number: Optional[str] = Field(default=None, description="Unique policy certificate number")
    policy_holder_name: Optional[str] = Field(default=None, description="Employer / organization name holding the policy")
    start_date: Optional[str] = Field(default=None, description="Policy inception/start date (DD/MM/YYYY, DD-Mon-YYYY or YYYY-MM-DD)")
    end_date: Optional[str] = Field(default=None, description="Policy expiry/end date (DD/MM/YYYY, DD-Mon-YYYY or YYYY-MM-DD)")
    policy_tenure_days: Optional[int] = Field(default=None, description="Duration of policy tenure in days (approx 365 for 1 yr)")
    is_renewal: Optional[bool] = Field(default=None, description="True if policy mentions renewal/rollover, else False")
    previous_policy_number: Optional[str] = Field(default=None, description="Previous policy number if renewal, else null")
    family_structure: Optional[str] = Field(
        default=None,
        description="Covered family construct, e.g. '1+3', 'Self + Spouse + 2 Children', 'Self + Spouse + 4 Dependent children'"
    )
    sum_insured_tiers: List[float] = Field(
        default_factory=list,
        description="Distinct numeric Sum Insured options/tiers available across member groups"
    )


class PremiumDetails(BaseModel):
    """Premium and financial details."""
    net_premium: Optional[float] = Field(default=None, description="Base/net premium before taxes in INR")
    gst_amount: Optional[float] = Field(default=None, description="Goods and Services Tax (GST / CGST / IGST / SGST) amount in INR")
    total_premium: Optional[float] = Field(default=None, description="Total gross premium payable including taxes in INR")
    payment_frequency: Optional[str] = Field(default=None, description="Payment schedule, e.g. 'Annual', 'Monthly'")


class DemographicsDetails(BaseModel):
    """Covered member demographic statistics."""
    total_employees: Optional[int] = Field(default=None, description="Count of primary insured employees/members")
    total_spouses: Optional[int] = Field(default=None, description="Count of covered spouses")
    total_children: Optional[int] = Field(default=None, description="Count of covered dependent children")
    total_parents: Optional[int] = Field(default=None, description="Count of covered parents / parents-in-law")
    total_dependents: Optional[int] = Field(default=None, description="Total count of all dependents (spouses + children + parents)")
    total_lives: Optional[int] = Field(default=None, description="Grand total of all insured lives covered")


class PolicyFeatures(BaseModel):
    """
    All required GMC insurance features and benefits.
    Every field uses the identical FeatureBenefit shape.
    """
    # A. Room Rent & Hospitalization
    room_rent: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Normal room rent eligibility, percentage of SI, monetary cap, or no limit"
    )
    icu_charges: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="ICU / ICCU room charges eligibility, percentage of SI, monetary cap, or no limit"
    )
    pre_hospitalization: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Pre-hospitalization medical expenses coverage duration in days"
    )
    post_hospitalization: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Post-hospitalization medical expenses coverage duration in days"
    )

    # B. Maternity Benefits
    maternity_normal: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Normal delivery maternity limit, sub-limits, or status"
    )
    maternity_c_section: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Caesarean section delivery maternity limit, sub-limits, or status"
    )
    maternity_waiting_period_9m: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="9-month maternity waiting period: 'waived' or 'applied'"
    )
    baby_day_one_cover: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Newborn baby covered from Day 1 / birth"
    )
    vaccination_coverage: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Newborn / child vaccination coverage and limits"
    )

    # C. Waiting Periods
    waiting_period_30_days: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Initial 30-day waiting period: 'waived', 'applied', or 'not_covered'"
    )
    waiting_period_first_second_year: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="1st / 2nd year specific ailment waiting periods: 'waived' or 'applied'"
    )
    pre_existing_diseases: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Pre-existing diseases (PED) waiting period: 'waived', 'covered', or 'applied'"
    )

    # D. Other Benefits
    day_care_expenses: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Day care treatments / procedures not requiring 24h hospitalization"
    )
    opd_benefit: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Outpatient department (OPD) consultation, diagnostics, and dental coverage"
    )
    teleconsultation: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Telephonic / virtual doctor consultation services"
    )
    pharmacy_discount: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Prescription medicine / pharmacy discount benefit"
    )
    domiciliary_hospitalization: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Medical treatment at home when hospital bed is unavailable or patient cannot be moved"
    )
    annual_health_checkup: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Annual health check-up or wellness screening"
    )
    modern_treatment: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Advanced modern treatments / robotic surgery / stem cell therapy"
    )
    bariatric_treatment: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Bariatric surgery / obesity treatment coverage and conditions"
    )
    psychiatric_treatment: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Mental illness and psychiatric disorders hospitalization cover"
    )
    ayush_treatment: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Ayurveda, Yoga, Unani, Siddha, and Homeopathy in-patient treatments"
    )
    lgbtq_live_in_partners: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Coverage extending to LGBTQ+ spouses, same-sex partners, or live-in partners"
    )
    organ_donor_expenses: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Hospitalization expenses incurred for organ donor during harvesting"
    )

    # E. Infertility & Ambulance Benefits
    infertility_treatment: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Infertility / IVF treatment coverage status and limits"
    )
    surrogacy_treatment: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Surrogacy and related medical expense coverage"
    )
    ambulance_charges: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Road ambulance charges per hospitalization event"
    )
    air_ambulance_charges: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Air ambulance emergency transportation coverage and limits"
    )

    # F. Buffer & Waiver Details
    corporate_buffer: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Corporate buffer / employer critical illness floater pool limit"
    )
    disease_wise_capping: FeatureBenefit = Field(
        default_factory=FeatureBenefit,
        description="Disease-wise capping (e.g. cataract, hernia, cardiac procedures) limits"
    )


class GMCPolicyExtraction(BaseModel):
    """
    Top-level structured extraction output for a Group Medical Cover policy document.
    """
    is_gmc_policy: bool = Field(
        default=True,
        description="True if document is a Group Medical Cover / Health policy; False if GPA, GTL, or other insurance"
    )
    policy_type: str = Field(
        default="Group Medical Cover",
        description="Detected policy type: 'Group Medical Cover', 'Group Personal Accident', 'Group Term Life', etc."
    )
    flag_notes: Optional[str] = Field(
        default=None,
        description="Explanation when policy is flagged as non-GMC or has critical missing sections"
    )
    insurer_name: Optional[str] = Field(
        default=None,
        description="Identified insurance company name"
    )
    tpa_name: Optional[str] = Field(
        default=None,
        description="Identified Third Party Administrator (TPA) or In-House Claims Servicing Team"
    )
    policy_details: PolicyDetails = Field(
        default_factory=PolicyDetails,
        description="Header and tenure details"
    )
    premium: PremiumDetails = Field(
        default_factory=PremiumDetails,
        description="Premium financial breakdown"
    )
    demographics: DemographicsDetails = Field(
        default_factory=DemographicsDetails,
        description="Insured lives and dependent counts"
    )
    features: PolicyFeatures = Field(
        default_factory=PolicyFeatures,
        description="All extracted benefit features and waiting periods"
    )
    source_file: str = Field(
        default="",
        description="Filename of the source PDF document"
    )
    total_pages: int = Field(
        default=0,
        description="Total page count of the source PDF"
    )
    validation_status: str = Field(
        default="PENDING",
        description="Validation outcome: PASSED, PASSED_WITH_WARNINGS, or FAILED"
    )
    validation_messages: List[str] = Field(
        default_factory=list,
        description="List of messages, warnings, or discrepancies caught during rule-based validation"
    )
