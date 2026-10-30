"""
main.py - CLI entrypoint for Group Medical Cover (GMC) insurance policy data extraction.

Usage:
    python main.py --input samples/ --output outputs/
    python main.py --input "samples/1.Policy Copy.pdf" --output outputs/
"""

import argparse
import csv
import glob
import json
import os
import sys
import time
from typing import List

from dotenv import load_dotenv

from src.extractor import extract_pdf_content
from src.classifier import PolicyClassifier
from src.llm import extract_gmc_policy_data, get_genai_client, DEFAULT_MODEL
from src.schema import GMCPolicyExtraction

load_dotenv()


def clean_output_stem(filename: str) -> str:
    """Converts a PDF filename into a clean output file stem."""
    base = os.path.splitext(os.path.basename(filename))[0]
    # Replace spaces and special characters with underscores
    cleaned = base.replace(" ", "_").replace(".", "_")
    return cleaned


def export_summary_csv(extractions: List[GMCPolicyExtraction], output_csv_path: str) -> None:
    """Exports a tabular summary of extracted policies to CSV."""
    fieldnames = [
        "filename",
        "is_gmc_policy",
        "policy_type",
        "insurer_name",
        "tpa_name",
        "policy_number",
        "policy_holder_name",
        "start_date",
        "end_date",
        "sum_insured_tiers",
        "total_lives",
        "net_premium",
        "total_premium",
        "room_rent_status",
        "room_rent_percent",
        "icu_status",
        "icu_percent",
        "pre_hosp_days",
        "post_hosp_days",
        "maternity_normal_limit",
        "maternity_c_section_limit",
        "maternity_9m_wait",
        "ped_status",
        "wait_30d_status",
        "corporate_buffer_status",
        "validation_status",
        "flag_notes"
    ]

    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in extractions:
            p_det = item.policy_details
            prem = item.premium
            feats = item.features
            row = {
                "filename": item.source_file,
                "is_gmc_policy": item.is_gmc_policy,
                "policy_type": item.policy_type,
                "insurer_name": item.insurer_name,
                "tpa_name": item.tpa_name,
                "policy_number": p_det.policy_number,
                "policy_holder_name": p_det.policy_holder_name,
                "start_date": p_det.start_date,
                "end_date": p_det.end_date,
                "sum_insured_tiers": "; ".join(str(s) for s in p_det.sum_insured_tiers),
                "total_lives": item.demographics.total_lives,
                "net_premium": prem.net_premium,
                "total_premium": prem.total_premium,
                "room_rent_status": feats.room_rent.status.value,
                "room_rent_percent": feats.room_rent.limit_percent_si,
                "icu_status": feats.icu_charges.status.value,
                "icu_percent": feats.icu_charges.limit_percent_si,
                "pre_hosp_days": feats.pre_hospitalization.days,
                "post_hosp_days": feats.post_hospitalization.days,
                "maternity_normal_limit": feats.maternity_normal.limit_amount,
                "maternity_c_section_limit": feats.maternity_c_section.limit_amount,
                "maternity_9m_wait": feats.maternity_waiting_period_9m.status.value,
                "ped_status": feats.pre_existing_diseases.status.value,
                "wait_30d_status": feats.waiting_period_30_days.status.value,
                "corporate_buffer_status": feats.corporate_buffer.status.value,
                "validation_status": item.validation_status,
                "flag_notes": item.flag_notes or ""
            }
            writer.writerow(row)


def process_single_pdf(
    pdf_path: str,
    output_dir: str,
    classifier: PolicyClassifier,
    client: any,
    model_name: str,
    enable_reprompt: bool,
    verbose: bool
) -> GMCPolicyExtraction:
    """Processes a single PDF file end-to-end."""
    filename = os.path.basename(pdf_path)
    print(f"\n========================================================")
    print(f"[*] Processing: {filename}")
    start_time = time.time()

    # 1. Extraction
    print("  [1/4] Extracting text and Markdown tables with pdfplumber...")
    extracted_pdf = extract_pdf_content(pdf_path)
    print(f"        Extracted {extracted_pdf.total_pages} pages, {len(extracted_pdf.full_text)} characters.")

    # 2. Classification Hint
    print("  [2/4] Running regex insurer/TPA pre-detection and policy classification...")
    hint = classifier.analyze(extracted_pdf.full_text)
    print(f"        Detected Insurer: {hint.insurer_hint}")
    print(f"        Detected TPA:     {hint.tpa_hint}")
    print(f"        Policy Type:      {hint.policy_type} (is_gmc={hint.is_gmc})")
    if hint.flag_notes:
        print(f"        Notice:           {hint.flag_notes}")

    # 3. Extraction & Validation
    print(f"  [3/4] Calling Gemini ({model_name}) with structured Pydantic output...")
    extraction = extract_gmc_policy_data(
        full_text=extracted_pdf.full_text,
        pages_text=extracted_pdf.pages_text,
        total_pages=extracted_pdf.total_pages,
        filename=filename,
        hint=hint,
        client=client,
        model_name=model_name,
        enable_reprompt=enable_reprompt
    )

    # 4. Save JSON Output
    print(f"  [4/4] Validation Status: {extraction.validation_status}")
    if extraction.validation_messages:
        for msg in extraction.validation_messages[:3]:
            print(f"        - {msg}")
        if len(extraction.validation_messages) > 3:
            print(f"        - ... and {len(extraction.validation_messages) - 3} more messages")

    os.makedirs(output_dir, exist_ok=True)
    stem = clean_output_stem(filename)
    output_json_path = os.path.join(output_dir, f"{stem}_extracted.json")

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(extraction.model_dump(), f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    print(f"[+] Saved output to: {output_json_path} ({elapsed:.1f}s)")
    return extraction


def main():
    parser = argparse.ArgumentParser(
        description="Extract structured insurance policy data from GMC and GPA policy PDFs using Gemini and pdfplumber."
    )
    parser.add_argument(
        "--input",
        type=str,
        default="samples/",
        help="Path to an input PDF file or a folder containing PDF files (default: samples/)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="outputs/",
        help="Directory to save extracted JSON files and summary.csv (default: outputs/)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Gemini model to use for extraction (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--no-reprompt",
        action="store_true",
        help="Disable targeted re-prompting pass for failed validation fields"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed logging output"
    )

    args = parser.parse_args()

    # Check API key
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("\n" + "=" * 60)
        print("[ERROR] GEMINI_API_KEY is not set.")
        print("This tool requires Google Gemini structured extraction.")
        print("Please set your GEMINI_API_KEY in a .env file or environment variable:")
        print("  Windows PowerShell:  $env:GEMINI_API_KEY=\"your_api_key_here\"")
        print("  Command Prompt:      set GEMINI_API_KEY=your_api_key_here")
        print("  Or add to .env file: GEMINI_API_KEY=your_api_key_here")
        print("=" * 60 + "\n")
        sys.exit(1)

    client = get_genai_client(api_key=api_key)

    classifier = PolicyClassifier()

    # Collect PDF files to process
    pdf_files = []
    if os.path.isfile(args.input):
        if args.input.lower().endswith(".pdf"):
            pdf_files.append(args.input)
        else:
            print(f"[ERROR] Input file '{args.input}' is not a PDF.")
            sys.exit(1)
    elif os.path.isdir(args.input):
        pattern = os.path.join(args.input, "*.pdf")
        pdf_files = glob.glob(pattern)
        if not pdf_files:
            print(f"[WARNING] No PDF files found in directory: {args.input}")
            sys.exit(0)
    else:
        print(f"[ERROR] Input path '{args.input}' does not exist.")
        sys.exit(1)

    print(f"\n========================================================")
    print(f"GMC Policy Extractor CLI")
    print(f"Input path:        {args.input}")
    print(f"Total PDFs found:  {len(pdf_files)}")
    print(f"Output directory:  {args.output}")
    print(f"Model:             {args.model}")
    print(f"Re-prompting:      {'Disabled' if args.no_reprompt else 'Enabled'}")
    print(f"========================================================")

    all_extractions: List[GMCPolicyExtraction] = []
    failed_files: List[str] = []
    for pdf_path in pdf_files:
        try:
            extraction = process_single_pdf(
                pdf_path=pdf_path,
                output_dir=args.output,
                classifier=classifier,
                client=client,
                model_name=args.model,
                enable_reprompt=not args.no_reprompt,
                verbose=args.verbose
            )
            all_extractions.append(extraction)
        except Exception as e:
            failed_files.append(os.path.basename(pdf_path))
            print(f"\n[!] Failed processing '{os.path.basename(pdf_path)}': {str(e)}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Write summary CSV
    if all_extractions:
        summary_csv_path = os.path.join(args.output, "summary.csv")
        export_summary_csv(all_extractions, summary_csv_path)
        print(f"\n[+] Generated summary CSV at: {summary_csv_path}")

    if failed_files:
        print(f"\n[FAILURE] Failed to extract {len(failed_files)} out of {len(pdf_files)} document(s): {', '.join(failed_files)}")
        sys.exit(1)

    print("\n[SUCCESS] Extraction completed for all documents.")


if __name__ == "__main__":
    main()
