"""
extractor.py - Extracts text and structured Markdown tables from insurance policy PDFs.
Preserves page numbers, table layout, and cleans artifact noise.
"""

import re
from typing import Dict, List, Tuple, Optional
import pdfplumber


# Known noisy watermark lines to strip (e.g. Liberty backwards watermark)
WATERMARK_PHRASES = [
    r"\.noitaticilos",
    r"rettam\s+tcejbus\s+eht\s+si\s+ecnarusnI",
    r"fo\s+rettam\s+tcejbus",
    r"lareneG\s+ytrebiL",
    r"lautuM\s+ytrebiL",
    r"ogoL\s+edarT"
]


def table_to_markdown(table: List[List[Optional[str]]]) -> str:
    """
    Converts a 2D table grid (extracted by pdfplumber) into clean GitHub-flavored Markdown.
    """
    if not table or not any(table):
        return ""

    # Clean cells: replace newlines with space, strip whitespace, replace None with ""
    cleaned_rows = []
    max_cols = 0
    for row in table:
        if not row:
            continue
        cleaned_row = []
        for cell in row:
            c = "" if cell is None else str(cell).replace("\n", " ").replace("|", "\\|").strip()
            # Collapse multiple spaces
            c = re.sub(r"\s+", " ", c)
            cleaned_row.append(c)
        max_cols = max(max_cols, len(cleaned_row))
        cleaned_rows.append(cleaned_row)

    if not cleaned_rows:
        return ""

    # Normalize column lengths
    for row in cleaned_rows:
        while len(row) < max_cols:
            row.append("")

    # Filter out empty rows where all cells are empty
    valid_rows = [r for r in cleaned_rows if any(cell.strip() for cell in r)]
    if not valid_rows:
        return ""

    # Build markdown
    header = valid_rows[0]
    separator = ["---"] * max_cols
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |"
    ]
    for row in valid_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def clean_page_text(raw_text: str) -> str:
    """
    Cleans raw page text by removing vertical backwards watermarks
    and excessive trailing blank lines.
    """
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    cleaned_lines = []
    
    # Check for backward watermark sequence
    skip_watermark_words = {
        ".noitaticilos", "fo", "rettam", "tcejbus", "eht", "si", "ecnarusnI",
        ".esnecil", "rednu", "detimiL", "lareneG", "ytrebiL", "yb", "desu",
        "dna", "lautuM", "ot", "sgnoleb", "evoba", "deyalpsid", "ogoL", "edarT"
    }

    for line in lines:
        stripped = line.strip()
        # If single isolated word from backwards watermark list, skip it
        if stripped in skip_watermark_words:
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    # Collapse 3+ newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class PDFExtractionResult:
    """Holds extraction results for a PDF document."""
    def __init__(self, full_text: str, pages_text: Dict[int, str], total_pages: int, tables_by_page: Dict[int, List[str]]):
        self.full_text = full_text
        self.pages_text = pages_text
        self.total_pages = total_pages
        self.tables_by_page = tables_by_page


import pymupdf


def detect_intra_word_spacing(text: str) -> bool:
    """
    Detects whether text contains stray intra-word spaces (kerning artifacts)
    with uppercase-initial split words (e.g. 'N orm al', 'H ospital', 'M edical').
    Ignores valid single-letter English words ('A', 'I', 'a', 'i') as well as
    isolated section/annexure labels ('Annexure B', 'Part B').
    """
    if not text:
        return False
    # Match uppercase-initial split words (excluding real single-letter English words 'A' and 'I'):
    # 1. Multi-split words with short syllables: [B-HJ-Z] \s+ [a-z]{1,4} \s+ [a-z]+ (e.g. 'N orm al', 'P lu s')
    # 2. Single-split words with uppercase initial: [B-HJ-Z] \s+ [a-z]{2,} (e.g. 'H ospitalization', 'M edical')
    matches = re.findall(
        r"(?<!\bAnnexure\s)(?<!\bPart\s)(?<!\bSection\s)\b[B-HJ-Z]\s+[a-z]{1,4}\s+[a-z]+(?:\s+[a-z]+)*\b|"
        r"(?<!\bAnnexure\s)(?<!\bPart\s)(?<!\bSection\s)\b[B-HJ-Z]\s+[a-z]{2,}\b",
        text
    )
    return len(matches) >= 3



def extract_pdf_content(pdf_path: str) -> PDFExtractionResult:
    """
    Extracts text and tables from a PDF using pdfplumber with PyMuPDF as a secondary extractor.
    When pdfplumber text shows intra-word spacing artifacts, merges the clean PyMuPDF text stream.
    Returns full markdown text, per-page text dictionary (1-indexed), and total pages.
    """
    pages_text: Dict[int, str] = {}
    tables_by_page: Dict[int, List[str]] = {}
    full_text_parts: List[str] = []

    # 1. Secondary clean text extraction using PyMuPDF
    pymupdf_pages: Dict[int, str] = {}
    try:
        with pymupdf.open(pdf_path) as doc:
            for idx, page in enumerate(doc):
                pymupdf_pages[idx + 1] = clean_page_text(page.get_text() or "")
    except Exception:
        pass

    # 2. Primary layout & table extraction using pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1
            raw_text = page.extract_text() or ""
            cleaned_text = clean_page_text(raw_text)

            # Extract tables
            page_tables_md: List[str] = []
            try:
                tables = page.extract_tables() or []
                for t_idx, table in enumerate(tables):
                    md = table_to_markdown(table)
                    if md:
                        page_tables_md.append(f"**Table {page_num}.{t_idx + 1}:**\n{md}")
            except Exception:
                pass

            tables_by_page[page_num] = page_tables_md

            # Check if pdfplumber text shows intra-word spacing
            mupdf_text = pymupdf_pages.get(page_num, "")
            combined_page_parts: List[str] = []

            if detect_intra_word_spacing(cleaned_text) and mupdf_text.strip():
                # Merge clean PyMuPDF text stream with pdfplumber tabular layout
                combined_page_parts.append("### Clean Text Stream (PyMuPDF):\n" + mupdf_text)
                combined_page_parts.append("### Layout & Tables (pdfplumber):\n" + cleaned_text)
            else:
                combined_page_parts.append(cleaned_text)

            if page_tables_md:
                combined_page_parts.append(f"\n\n### Tables on Page {page_num}:\n" + "\n\n".join(page_tables_md))

            page_full_content = "\n\n".join(p for p in combined_page_parts if p.strip())
            pages_text[page_num] = page_full_content

            formatted_page = f"--- PAGE {page_num} OF {total_pages} ---\n{page_full_content}\n--- END PAGE {page_num} ---"
            full_text_parts.append(formatted_page)

    full_text = "\n\n".join(full_text_parts)
    return PDFExtractionResult(
        full_text=full_text,
        pages_text=pages_text,
        total_pages=total_pages,
        tables_by_page=tables_by_page
    )
