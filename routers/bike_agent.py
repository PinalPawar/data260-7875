"""
HW7 Part 4: web UI routes for the Bay Wheels membership agent.

    GET  /bike            the page (CSV upload, pricing URL, Run, timeline, results, metrics)
    POST /api/bike/run    multipart form: csv (file), url (text) -> the agent run as JSON

Each run is also saved to reports/hw07/raw/part4_runs/ so the reported results have raw data.
The endpoint is a plain def, so FastAPI runs the (slow) local model in its thread pool.
"""
import json
import os
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from bike_agent.agent import make_model, run_bike_agent

router = APIRouter(tags=["bike-agent"])
UI_FILE = os.path.join("bike_agent", "ui.html")
RUN_DIR = os.path.join("reports", "hw07", "raw", "part4_runs")
DEFAULT_URL = "https://www.lyft.com/bikes/bay-wheels/pricing"
MAX_CSV_BYTES = 20 * 1024 * 1024
ALLOWED_MODELS = {"qwen3:1.7b", "qwen3:8b"}


@router.get("/bike")
def bike_page() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(UI_FILE)


@router.post("/api/bike/run")
def run_bike(csv: UploadFile = File(...), url: str = Form(DEFAULT_URL),
             model: str = Form("qwen3:8b")) -> dict:
    """Run the agent on the uploaded trips and the pricing URL; save and return the result."""
    if model not in ALLOWED_MODELS:
        allowed = ", ".join(sorted(ALLOWED_MODELS))
        raise HTTPException(status_code=400, detail=f"model must be one of: {allowed}")
    raw = csv.file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV larger than 20 MB")
    try:
        text = raw.decode("utf-8-sig")
        result = run_bike_agent(text, url.strip() or DEFAULT_URL, model=make_model(model))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 text")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result["input"] = {"csv_name": csv.filename, "csv_bytes": len(raw), "url": url}
    result["saved_to"] = save_run(result, csv.filename or "upload.csv")
    return result


def save_run(result: dict, csv_name: str) -> str:
    """Write one run's full result JSON (timeline, answer, check, snapshot) to the raw folder."""
    os.makedirs(RUN_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(csv_name))[0]
    path = os.path.join(RUN_DIR, f"run_{datetime.now():%Y%m%d_%H%M%S}_{stem}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    return path
