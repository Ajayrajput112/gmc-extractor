"""
test_classifier.py - Unit tests for regex hints and policy classification.
"""

from src.classifier import PolicyClassifier


def test_detect_known_insurers():
    """Verify detection of various insurer names via regex."""
    classifier = PolicyClassifier()

    assert classifier.detect_insurer("Care Health Insurance Limited Direct") == "Care Health Insurance Limited"
    assert classifier.detect_insurer("formerly Religare Health Insurance Company") == "Care Health Insurance Limited"
    assert classifier.detect_insurer("Niva Bupa Health Insurance Company Limited") == "Niva Bupa Health Insurance Company Limited"
    assert classifier.detect_insurer("LIBERTY GENERAL INSURANCE LIMITED") == "Liberty General Insurance Limited"
    assert classifier.detect_insurer("Tata AIG General Insurance Co. Ltd.") == "Tata AIG General Insurance Company Limited"


def test_detect_known_tpas():
    """Verify detection of known TPAs via regex."""
    classifier = PolicyClassifier()

    assert classifier.detect_tpa("Claims processed by Medi Assist Insurance TPA") == "Medi Assist Insurance TPA Private Limited"
    assert classifier.detect_tpa("Vidal Health TPA Private Ltd") == "Vidal Health Insurance TPA Private Limited"
    assert classifier.detect_tpa("Paramount Health Services & Insurance TPA") == "Paramount Health Services & Insurance TPA Private Limited"


def test_classify_gpa_policy():
    """Verify that a Group Personal Accident document is flagged as non-GMC."""
    classifier = PolicyClassifier()
    text = (
        "LIBERTY GROUP PERSONAL ACCIDENT POLICY - POLICY SCHEDULE\n"
        "Accidental Death - Covers Death due to Accident.\n"
        "Permanent Total Disability Covers Permanent Total Disablement."
    )
    is_gmc, policy_type, flag_notes = classifier.classify_policy_type(text)
    assert is_gmc is False
    assert policy_type == "Group Personal Accident"
    assert "Group Personal Accident" in flag_notes


def test_classify_gmc_policy():
    """Verify that a Group Medical Cover document is classified as GMC."""
    classifier = PolicyClassifier()
    text = (
        "Policy Certificate - Group Care 360\n"
        "Benefits: In-patient Care, Room Rent, Pre-hospitalization, Post-hospitalization\n"
        "Pre-existing diseases are covered for existing members."
    )
    is_gmc, policy_type, flag_notes = classifier.classify_policy_type(text)
    assert is_gmc is True
    assert policy_type == "Group Medical Cover"
    assert flag_notes is None
