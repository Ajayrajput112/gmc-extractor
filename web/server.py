"""
server.py - FastAPI backend for GMC Policy Intelligence Dashboard.
Provides endpoints for live PDF extraction, policy exploration, comparative visual analytics,
and summary exports.
"""

import csv
import json
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from src.extractor import extract_pdf_content
from src.classifier import PolicyClassifier
from src.llm import extract_gmc_policy_data, get_genai_client, DEFAULT_MODEL
from src.schema import GMCPolicyExtraction

load_dotenv()

app = FastAPI(
    title="GMC Policy Intelligence API",
    description="Automated Insurance Document Intelligence & Analytics Platform",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUTS_DIR = os.path.abspath("outputs")
SAMPLES_DIR = os.path.abspath("samples")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

classifier = PolicyClassifier()


def clean_output_stem(filename: str) -> str:
    """Sanitizes filename for clean output naming."""
    import re
    stem = os.path.splitext(filename)[0]
    return re.sub(r"[^\w\-.]", "_", stem)


def update_summary_csv(extractions: List[GMCPolicyExtraction], output_csv_path: str):
    """Updates the summary CSV with the latest policy extractions."""
    fieldnames = [
        "filename", "is_gmc_policy", "policy_type", "insurer_name", "tpa_name",
        "policy_number", "policy_holder_name", "start_date", "end_date",
        "sum_insured_tiers", "total_lives", "net_premium", "total_premium",
        "room_rent_status", "room_rent_percent", "icu_status", "icu_percent",
        "pre_hosp_days", "post_hosp_days", "maternity_normal_limit",
        "maternity_c_section_limit", "maternity_9m_wait", "ped_status",
        "wait_30d_status", "corporate_buffer_status", "validation_status", "flag_notes"
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
                "insurer_name": item.insurer_name or "",
                "tpa_name": item.tpa_name or "",
                "policy_number": p_det.policy_number or "",
                "policy_holder_name": p_det.policy_holder_name or "",
                "start_date": p_det.start_date or "",
                "end_date": p_det.end_date or "",
                "sum_insured_tiers": "; ".join(str(s) for s in p_det.sum_insured_tiers),
                "total_lives": item.demographics.total_lives or "",
                "net_premium": prem.net_premium or "",
                "total_premium": prem.total_premium or "",
                "room_rent_status": feats.room_rent.status.value,
                "room_rent_percent": feats.room_rent.limit_percent_si or "",
                "icu_status": feats.icu_charges.status.value,
                "icu_percent": feats.icu_charges.limit_percent_si or "",
                "pre_hosp_days": feats.pre_hospitalization.days or "",
                "post_hosp_days": feats.post_hospitalization.days or "",
                "maternity_normal_limit": feats.maternity_normal.limit_amount or "",
                "maternity_c_section_limit": feats.maternity_c_section.limit_amount or "",
                "maternity_9m_wait": feats.maternity_waiting_period_9m.status.value,
                "ped_status": feats.pre_existing_diseases.status.value,
                "wait_30d_status": feats.waiting_period_30_days.status.value,
                "corporate_buffer_status": feats.corporate_buffer.status.value,
                "validation_status": item.validation_status,
                "flag_notes": item.flag_notes or ""
            }
            writer.writerow(row)


@app.get("/api/health")
def health_check():
    """Health check and model configuration status."""
    has_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return {
        "status": "online",
        "api_key_configured": has_key,
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "outputs_count": len([f for f in os.listdir(OUTPUTS_DIR) if f.endswith(".json")]) if os.path.exists(OUTPUTS_DIR) else 0
    }


@app.get("/api/policies")
def list_policies():
    """Returns a list of all extracted policies currently saved in outputs/."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    policies = []
    for fname in sorted(os.listdir(OUTPUTS_DIR)):
        if fname.endswith(".json"):
            fpath = os.path.join(OUTPUTS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                policies.append({
                    "id": clean_output_stem(fname),
                    "file_name": fname,
                    "source_file": data.get("source_file", fname),
                    "is_gmc_policy": data.get("is_gmc_policy", True),
                    "policy_type": data.get("policy_type", "Unknown"),
                    "insurer_name": data.get("insurer_name") or "Not Identified",
                    "policy_number": data.get("policy_details", {}).get("policy_number") or "N/A",
                    "policy_holder_name": data.get("policy_details", {}).get("policy_holder_name") or "N/A",
                    "start_date": data.get("policy_details", {}).get("start_date"),
                    "end_date": data.get("policy_details", {}).get("end_date"),
                    "total_lives": data.get("demographics", {}).get("total_lives"),
                    "net_premium": data.get("premium", {}).get("net_premium"),
                    "total_premium": data.get("premium", {}).get("total_premium"),
                    "validation_status": data.get("validation_status", "UNKNOWN"),
                    "total_features_covered": sum(
                        1 for f in data.get("features", {}).values()
                        if isinstance(f, dict) and f.get("status") in ("covered", "waived", "applied")
                    )
                })
            except Exception as e:
                continue
    return policies


@app.get("/api/policy/{policy_id}")
def get_policy_detail(policy_id: str):
    """Retrieves full extraction JSON for a specific policy."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    # Search for matching file
    target_file = None
    for fname in os.listdir(OUTPUTS_DIR):
        if fname.endswith(".json") and (fname == policy_id or clean_output_stem(fname) == policy_id or fname.startswith(policy_id)):
            target_file = os.path.join(OUTPUTS_DIR, fname)
            break

    if not target_file or not os.path.exists(target_file):
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")

    with open(target_file, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/extract")
async def upload_and_extract(file: UploadFile = File(...)):
    """
    Accepts an uploaded PDF document, processes it through the extraction & validation pipeline,
    saves the output to outputs/, updates summary.csv, and returns the extracted JSON.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF documents are supported.")

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    start_time = time.time()

    # Save uploaded file to a temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        # 1. PDF Extraction
        extracted_pdf = extract_pdf_content(tmp_path)

        # 2. Classifier Hint
        hint = classifier.analyze(extracted_pdf.full_text)

        # 3. LLM Extraction & Validation
        client = get_genai_client()
        model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

        extraction = extract_gmc_policy_data(
            full_text=extracted_pdf.full_text,
            pages_text=extracted_pdf.pages_text,
            total_pages=extracted_pdf.total_pages,
            filename=file.filename,
            hint=hint,
            client=client,
            model_name=model_name,
            enable_reprompt=True
        )

        # 4. Save to outputs directory
        stem = clean_output_stem(file.filename)
        output_json_path = os.path.join(OUTPUTS_DIR, f"{stem}_extracted.json")
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(extraction.model_dump(), f, indent=2, ensure_ascii=False)

        # 5. Update summary CSV
        all_extractions = []
        for fname in sorted(os.listdir(OUTPUTS_DIR)):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(OUTPUTS_DIR, fname), "r", encoding="utf-8") as jf:
                        all_extractions.append(GMCPolicyExtraction.model_validate_json(jf.read()))
                except Exception:
                    pass
        update_summary_csv(all_extractions, os.path.join(OUTPUTS_DIR, "summary.csv"))

        elapsed = time.time() - start_time
        result = extraction.model_dump()
        result["processing_time_sec"] = round(elapsed, 2)
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.get("/api/summary")
def get_summary_metrics():
    """Aggregates high-level portfolio metrics and cross-policy comparisons."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    policies = []
    for fname in os.listdir(OUTPUTS_DIR):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(OUTPUTS_DIR, fname), "r", encoding="utf-8") as f:
                    policies.append(json.load(f))
            except Exception:
                continue

    total_policies = len(policies)
    gmc_count = sum(1 for p in policies if p.get("is_gmc_policy"))
    non_gmc_count = total_policies - gmc_count

    total_lives_portfolio = sum(
        p.get("demographics", {}).get("total_lives") or 0 for p in policies
    )
    total_premium_portfolio = sum(
        p.get("premium", {}).get("total_premium") or 0 for p in policies
    )

    # Benefit comparison matrix
    features_comparison = {}
    for p in policies:
        fname = p.get("source_file") or "Unnamed"
        features_comparison[fname] = {
            "insurer": p.get("insurer_name") or "Unknown",
            "policy_type": p.get("policy_type") or "GMC",
            "lives": p.get("demographics", {}).get("total_lives") or 0,
            "total_premium": p.get("premium", {}).get("total_premium") or 0,
            "cost_per_life": round(
                (p.get("premium", {}).get("total_premium") or 0) /
                max(p.get("demographics", {}).get("total_lives") or 1, 1), 2
            ),
            "room_rent": p.get("features", {}).get("room_rent", {}),
            "icu_charges": p.get("features", {}).get("icu_charges", {}),
            "pre_hosp_days": p.get("features", {}).get("pre_hospitalization", {}).get("days"),
            "post_hosp_days": p.get("features", {}).get("post_hospitalization", {}).get("days"),
            "maternity_normal": p.get("features", {}).get("maternity_normal", {}),
            "maternity_c_section": p.get("features", {}).get("maternity_c_section", {}),
            "maternity_9m_wait": p.get("features", {}).get("maternity_waiting_period_9m", {}).get("status"),
            "ped_status": p.get("features", {}).get("pre_existing_diseases", {}).get("status"),
            "wait_30d_status": p.get("features", {}).get("waiting_period_30_days", {}).get("status"),
            "corporate_buffer": p.get("features", {}).get("corporate_buffer", {}).get("status"),
            "validation_status": p.get("validation_status", "UNKNOWN")
        }

    return {
        "portfolio": {
            "total_policies": total_policies,
            "gmc_count": gmc_count,
            "non_gmc_count": non_gmc_count,
            "total_lives": total_lives_portfolio,
            "total_premium": total_premium_portfolio,
            "avg_premium_per_life": round(
                total_premium_portfolio / max(total_lives_portfolio, 1), 2
            ) if total_lives_portfolio > 0 else 0
        },
        "comparison_matrix": features_comparison
    }


@app.get("/api/download/csv")
def download_summary_csv():
    """Serves summary.csv download."""
    csv_path = os.path.join(OUTPUTS_DIR, "summary.csv")
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="summary.csv not found. Run extraction first.")
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename="gmc_policies_summary.csv"
    )


@app.get("/api/download/json")
def download_portfolio_json():
    """Serves compiled portfolio JSON containing all extracted policy data."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    policies = []
    for fname in sorted(os.listdir(OUTPUTS_DIR)):
        if fname.endswith(".json"):
            fpath = os.path.join(OUTPUTS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    policies.append(json.load(f))
            except Exception:
                continue

    summary_data = get_summary_metrics()
    export_payload = {
        "export_title": "GMC Insurance Policy Portfolio Extraction",
        "export_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "portfolio_summary": summary_data.get("portfolio", {}),
        "total_policies": len(policies),
        "policies": policies
    }

    content_str = json.dumps(export_payload, indent=2, ensure_ascii=False)
    return Response(
        content=content_str,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="gmc_portfolio_export.json"'}
    )


@app.get("/api/policy/{policy_id}/download")
def download_single_policy_json(policy_id: str):
    """Downloads full JSON extraction for a specific policy as an attachment."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    target_file = None
    for fname in os.listdir(OUTPUTS_DIR):
        if fname.endswith(".json") and (fname == policy_id or clean_output_stem(fname) == policy_id or fname.startswith(policy_id)):
            target_file = os.path.join(OUTPUTS_DIR, fname)
            break

    if not target_file or not os.path.exists(target_file):
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")

    filename = os.path.basename(target_file)
    return FileResponse(
        target_file,
        media_type="application/json",
        filename=filename
    )


# Mount static directory for frontend assets
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_index():
    """Serves the main single-page frontend application."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_file):
        return HTMLResponse("<h1>Frontend loading...</h1>", status_code=200)
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("🚀 Starting GMC Intelligence Dashboard on http://localhost:8000")
    print("=" * 60 + "\n")
    uvicorn.run("web.server:app", host="0.0.0.0", port=8000, reload=True)
