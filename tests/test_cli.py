"""
test_cli.py - Unit tests for CLI helpers and CSV export.
"""

import os
import tempfile
import csv
from main import clean_output_stem, export_summary_csv
from src.schema import GMCPolicyExtraction, PolicyDetails, PremiumDetails


def test_clean_output_stem():
    """Verify that filenames are cleaned appropriately for JSON filenames."""
    assert clean_output_stem("1.Policy Copy.pdf") == "1_Policy_Copy"
    assert clean_output_stem("Net Catalyst - GPA - Policy Copy - 2022-23.pdf") == "Net_Catalyst_-_GPA_-_Policy_Copy_-_2022-23"
    assert clean_output_stem("GHI Policy.pdf") == "GHI_Policy"


def test_export_summary_csv():
    """Verify that export_summary_csv writes proper CSV rows."""
    ext = GMCPolicyExtraction(
        source_file="test_policy.pdf",
        is_gmc_policy=True,
        policy_type="Group Medical Cover",
        insurer_name="Care Health Insurance Limited",
        tpa_name="In-House / Direct Insurer Claims Team",
        policy_details=PolicyDetails(
            policy_number="123456",
            policy_holder_name="Acme Corp",
            start_date="01-Apr-2023",
            end_date="31-Mar-2024",
            sum_insured_tiers=[500000.0]
        ),
        premium=PremiumDetails(
            net_premium=100000.0,
            total_premium=118000.0
        ),
        validation_status="PASSED"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_summary.csv")
        export_summary_csv([ext], csv_path)

        assert os.path.exists(csv_path)
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 1
            row = reader[0]
            assert row["filename"] == "test_policy.pdf"
            assert row["insurer_name"] == "Care Health Insurance Limited"
            assert row["policy_holder_name"] == "Acme Corp"
            assert row["sum_insured_tiers"] == "500000.0"
            assert row["validation_status"] == "PASSED"


def test_main_cli_exits_nonzero_on_failure(monkeypatch, capsys):
    """Verify that main.py exits with code 1 and prints [FAILURE] if a PDF fails."""
    import sys
    import pytest
    from unittest.mock import patch
    import main

    test_args = ["main.py", "--input", "samples/1.Policy Copy.pdf", "--output", "outputs/"]
    monkeypatch.setattr(sys, "argv", test_args)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")

    with patch("main.get_genai_client"):
        with patch("main.process_single_pdf", side_effect=RuntimeError("Extraction failed unexpectedly")):
            with pytest.raises(SystemExit) as exc_info:
                main.main()

            assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "[FAILURE]" in captured.out
    assert "[SUCCESS]" not in captured.out

