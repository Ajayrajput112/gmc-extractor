"""
test_extractor.py - Unit tests for pdfplumber table and text extraction.
"""

import os
from src.extractor import (
    table_to_markdown,
    clean_page_text,
    extract_pdf_content
)


def test_table_to_markdown_basic():
    """Test standard 2D table conversion into Markdown."""
    table = [
        ["Plan", "Room Rent", "ICU"],
        ["Tier 1", "2% SI", "4% SI"],
        ["Tier 2", "No Limit", "No Limit"]
    ]
    md = table_to_markdown(table)
    assert "| Plan | Room Rent | ICU |" in md
    assert "| --- | --- | --- |" in md
    assert "| Tier 1 | 2% SI | 4% SI |" in md
    assert "| Tier 2 | No Limit | No Limit |" in md


def test_table_to_markdown_with_newlines_and_nones():
    """Test table with linebreaks and None values."""
    table = [
        ["Header A", "Header B"],
        ["Line 1\nLine 2", None],
        [None, "Value B"]
    ]
    md = table_to_markdown(table)
    assert "Line 1 Line 2" in md
    assert "| Header A | Header B |" in md


def test_clean_page_text_watermark_removal():
    """Test that reversed watermark words are stripped while regular content is preserved."""
    sample_text = (
        ".noitaticilos\n"
        "fo\n"
        "rettam\n"
        "tcejbus\n"
        "eht\n"
        "GROUP PERSONAL ACCIDENT POLICY\n"
        "Policy Number: POL-TEST-12345\n"
        "lareneG\n"
        "ytrebiL\n"
    )
    cleaned = clean_page_text(sample_text)
    assert ".noitaticilos" not in cleaned
    assert "GROUP PERSONAL ACCIDENT POLICY" in cleaned
    assert "Policy Number: POL-TEST-12345" in cleaned


def test_extract_pdf_content_live_sample():
    """Test extract_pdf_content against samples/1.Policy Copy.pdf if available."""
    pdf_path = "samples/1.Policy Copy.pdf"
    if os.path.exists(pdf_path):
        res = extract_pdf_content(pdf_path)
        assert res.total_pages == 4
        assert 1 in res.pages_text
        assert 2 in res.pages_text
        assert len(res.full_text) > 500
        assert "--- PAGE 1 OF 4 ---" in res.full_text


def test_detect_intra_word_spacing():
    """Verify that detect_intra_word_spacing ignores standard English and detects split words."""
    from src.extractor import detect_intra_word_spacing

    # Normal English with 'a' and 'I' must NOT trigger
    normal_english = (
        "This policy covers a room up to a maximum limit for a period of 365 days. "
        "I confirm that an insured person admitted to a hospital receives a claim."
    )
    assert detect_intra_word_spacing(normal_english) is False

    # Section markers must NOT trigger
    section_markers = "Please refer to Annexure B under Know Your Policy and Part B forming schedule."
    assert detect_intra_word_spacing(section_markers) is False

    # Text with uppercase-initial split words (kerning artifacts) MUST trigger
    split_words_text = (
        "Coverage for N orm al delivery and H ospitalization in M edical center. "
        "Special P lu s plan with M em bers eligible after W aiting period."
    )
    assert detect_intra_word_spacing(split_words_text) is True


