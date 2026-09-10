"""
MVP entrypoint. No DB yet -- upload a file, get back profiled columns and
hybrid (deterministic + AI) mapping suggestions; validate runs
transformation + business-rule checks; export applies the finalized
mapping and returns a real target-shaped .xlsx. Run with:

    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/docs to try it via Swagger UI, or open
frontend/index.html (served, not double-clicked -- see README note on
CORS/downloads) in a browser.
"""

import json
import io

from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import pandas as pd

from app.excel_ingest import ingest
from app.hybrid_mapper import build_hybrid_suggestions
from app.target_schema import get_target_fields
from app.run_pipeline import run_pipeline

app = FastAPI(title="Generic Excel Mapper - MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before deploying anywhere real
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/target-schema")
def target_schema():
    """Expose the target template fields, e.g. for a frontend to render."""
    return [
        {
            "name": f.name,
            "description": f.description,
            "data_type": f.data_type,
            "required": f.required,
        }
        for f in get_target_fields()
    ]


@app.post("/upload")
async def upload(file: UploadFile = File(...), sheet_name: str | None = Query(default=None)):
    """
    Upload an Excel file and get back:
      - detected sheets / header row
      - profiled columns (inferred type, samples, null rate)
      - hybrid (deterministic + AI) mapping suggestions, each tagged with
        a status: auto_mapped / needs_review / unresolved
    """
    file_bytes = await file.read()

    ingestion_result = ingest(file_bytes, sheet_name=sheet_name)
    columns_for_matching = [
        {"name": c["name"], "sample_values": c["sample_values"]}
        for c in ingestion_result["columns"]
    ]

    target_fields = get_target_fields()
    hybrid_result = build_hybrid_suggestions(columns_for_matching, target_fields)

    return {
        "filename": file.filename,
        "ingestion": ingestion_result,
        "ai_available": hybrid_result["ai_available"],
        "mapping_suggestions": hybrid_result["suggestions"],
    }


@app.post("/validate")
async def validate(
    file: UploadFile = File(...),
    sheet_name: str = Form(...),
    header_row: int = Form(...),
    mapping_json: str = Form(...),
):
    """
    Applies the mapping, runs transformation then validation, and returns
    a run summary + full issue list (each issue tagged with its stage:
    "transformation" or "validation") for the review UI.
    """
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    target_fields = get_target_fields()

    result = run_pipeline(file_bytes, sheet_name, header_row, mapping, target_fields)

    return {
        **result["summary"],
        "issues": [i.to_dict() for i in result["issues"]],
    }


@app.post("/validate/report")
async def validate_report(
    file: UploadFile = File(...),
    sheet_name: str = Form(...),
    header_row: int = Form(...),
    mapping_json: str = Form(...),
):
    """Same computation as /validate, returned as a downloadable CSV."""
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    target_fields = get_target_fields()

    result = run_pipeline(file_bytes, sheet_name, header_row, mapping, target_fields)
    issues_df = pd.DataFrame([i.to_dict() for i in result["issues"]])
    if issues_df.empty:
        issues_df = pd.DataFrame(columns=[
            "row_index", "target_field", "rule_violated", "severity", "stage", "message", "raw_value"
        ])

    buffer = io.StringIO()
    issues_df.to_csv(buffer, index=False)
    csv_bytes = buffer.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=validation_error_report.csv"},
    )


@app.post("/export")
async def export(
    file: UploadFile = File(...),
    sheet_name: str = Form(...),
    header_row: int = Form(...),
    mapping_json: str = Form(...),
    skip_invalid_rows: bool = Form(default=False),
    save_as_profile: bool = Form(default=False),
    approve_for_learning: bool = Form(default=False),
):
    """
    Re-reads the source file (kept stateless -- no server-side storage
    yet), applies the finalized mapping, transforms, optionally drops
    rows with blocking issues, and returns a downloadable .xlsx.

    save_as_profile / approve_for_learning are accepted so the frontend
    can present the full "final run" screen your spec calls for, but
    NEITHER IS PERSISTED YET -- that requires the DB layer (models.py),
    which this MVP intentionally doesn't wire up. They're no-ops for now,
    not silently-faked behavior.
    """
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    target_fields = get_target_fields()

    result = run_pipeline(file_bytes, sheet_name, header_row, mapping, target_fields)
    output_df = result["transformed_df"]

    if skip_invalid_rows:
        output_df = output_df.drop(index=list(result["blocking_row_indices"]), errors="ignore")

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="Mapped Output")
    buffer.seek(0)

    # save_as_profile / approve_for_learning intentionally unused -- see docstring.

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=mapped_output.xlsx"},
    )