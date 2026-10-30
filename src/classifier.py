"""
classifier.py - Detects insurer, TPA, and classifies whether a document
is a Group Medical Cover (GMC) policy vs Group Personal Accident (GPA) or other policy.
Uses regex hints from config/insurers_tpa.json.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "insurers_tpa.json"
)


class ClassificationHint:
    """Pre-LLM classification hints derived from regex and config patterns."""
    def __init__(
        self,
        insurer_hint: Optional[str] = None,
        tpa_hint: Optional[str] = None,
        is_gmc: bool = True,
        policy_type: str = "Group Medical Cover",
        flag_notes: Optional[str] = None
    ):
        self.insurer_hint = insurer_hint
        self.tpa_hint = tpa_hint
        self.is_gmc = is_gmc
        self.policy_type = policy_type
        self.flag_notes = flag_notes

    def to_dict(self) -> Dict[str, any]:
        return {
            "insurer_hint": self.insurer_hint,
            "tpa_hint": self.tpa_hint,
            "is_gmc": self.is_gmc,
            "policy_type": self.policy_type,
            "flag_notes": self.flag_notes
        }


class PolicyClassifier:
    """Regex-based policy classifier and insurer/TPA hint detector."""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.insurers = []
        self.tpas = []
        self.policy_types = {}
        self._load_config()

    def _load_config(self) -> None:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.insurers = data.get("insurers", [])
        self.tpas = data.get("tpas", [])
        self.policy_types = data.get("policy_types", {})

    def detect_insurer(self, text: str) -> Optional[str]:
        """Scans text for registered insurer regex patterns."""
        for item in self.insurers:
            pattern = item.get("regex")
            if pattern and re.search(pattern, text, re.IGNORECASE):
                return item["name"]
        return None

    def detect_tpa(self, text: str) -> Optional[str]:
        """Scans text for registered TPA regex patterns."""
        for item in self.tpas:
            pattern = item.get("regex")
            if pattern and re.search(pattern, text, re.IGNORECASE):
                return item["name"]
        return None

    def classify_policy_type(self, text: str) -> Tuple[bool, str, Optional[str]]:
        """
        Determines whether the document is a GMC health policy or another policy type
        such as Group Personal Accident (GPA) or Group Term Life (GTL).
        Returns: (is_gmc, policy_type_name, flag_notes)
        """
        gpa_patterns = self.policy_types.get("gpa_indicators", [])
        gtl_patterns = self.policy_types.get("gtl_indicators", [])
        gmc_patterns = self.policy_types.get("gmc_indicators", [])

        # Count pattern occurrences
        gpa_matches = sum(1 for p in gpa_patterns if re.search(p, text, re.IGNORECASE))
        gtl_matches = sum(1 for p in gtl_patterns if re.search(p, text, re.IGNORECASE))
        gmc_matches = sum(1 for p in gmc_patterns if re.search(p, text, re.IGNORECASE))

        # Check explicit GPA mentions in title/header
        is_explicit_gpa = bool(
            re.search(r"\b(Group\s+Personal\s+Accident|LIBERTY\s+GROUP\s+PERSONAL\s+ACCIDENT)\b", text, re.IGNORECASE)
        )

        if is_explicit_gpa or (gpa_matches > 0 and gmc_matches == 0):
            return (
                False,
                "Group Personal Accident",
                "Flagged non-GMC policy: Document identified as 'Group Personal Accident'. It does not provide Group Medical Cover (GMC) health benefits."
            )

        if gtl_matches > 0 and gmc_matches == 0:
            return (
                False,
                "Group Term Life",
                "Flagged non-GMC policy: Document identified as 'Group Term Life'. It does not provide Group Medical Cover (GMC) health benefits."
            )

        return (True, "Group Medical Cover", None)

    def analyze(self, text: str) -> ClassificationHint:
        """Full pre-LLM classification hint analysis."""
        insurer = self.detect_insurer(text)
        tpa = self.detect_tpa(text)
        is_gmc, policy_type, flag_notes = self.classify_policy_type(text)

        # If TPA is not mentioned but direct claims team is present in Care Health
        if not tpa and insurer and "Care Health" in insurer:
            if re.search(r"Claims\s+Servicing\s+Team|Claims@careinsurance", text, re.IGNORECASE):
                tpa = "In-House / Direct Insurer Claims Team"

        return ClassificationHint(
            insurer_hint=insurer,
            tpa_hint=tpa,
            is_gmc=is_gmc,
            policy_type=policy_type,
            flag_notes=flag_notes
        )
