"""
MVP entrypoint. Templates are now DB-backed (SQLite) -- everything else
in the pipeline (ingestion, hybrid mapping, transform, validate, export)
is still stateless per-request, just fed by whichever template the
caller specifies. Run with:

    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/docs, or the frontend pages:
  frontend/templates.html -- manage templates
  frontend/index.html     -- upload + map + validate + export
"""

import json
import io

from fastapi import FastAPI, UploadFile, File, Form, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd

from app.database import Base, engine, SessionLocal, get_db
from app.excel_ingest import ingest
from app.hybrid_mapper import build_hybrid_suggestions
from app.run_pipeline import run_pipeline
from app.templates_api import router as templates_router
from app.template_service import get_target_fields_for_template, seed_default_template

app = FastAPI(title="Generic Excel Mapper - MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before deploying anywhere real
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(templates_router, prefix="/templates", tags=["templates"])


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_template(db)
    finally:
        db.close()


@app.get("/target-schema")
def target_schema(template_id: str | None = Query(default=None), db: Session = Depends(get_db)):
    """Expose a template's fields, e.g. for a frontend dropdown. Defaults
    to the current active template if template_id is omitted."""
    template, fields = get_target_fields_for_template(db, template_id)
    return {
        "template_id": template.id,
        "template_name": template.name,
        "template_version": template.version,
        "fields": [
            {"name": f.name, "description": f.description, "data_type": f.data_type, "required": f.required}
            for f in fields
        ],
    }


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    sheet_name: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Upload an Excel file and get back:
      - detected sheets / header row
      - profiled columns (inferred type, samples, null rate)
      - hybrid (deterministic + AI) mapping suggestions against the
        chosen (or default active) template, each tagged with a status:
        auto_mapped / needs_review / unresolved
    """
    file_bytes = await file.read()

    ingestion_result = ingest(file_bytes, sheet_name=sheet_name)
    columns_for_matching = [
        {"name": c["name"], "sample_values": c["sample_values"]}
        for c in ingestion_result["columns"]
    ]

    template, target_fields = get_target_fields_for_template(db, template_id)
    hybrid_result = build_hybrid_suggestions(columns_for_matching, target_fields)

    return {
        "filename": file.filename,
        "template_id": template.id,
        "template_name": template.name,
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
    template_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    _, target_fields = get_target_fields_for_template(db, template_id)

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
    template_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    _, target_fields = get_target_fields_for_template(db, template_id)

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
    template_id: str | None = Form(default=None),
    skip_invalid_rows: bool = Form(default=False),
    save_as_profile: bool = Form(default=False),
    approve_for_learning: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    """
    save_as_profile / approve_for_learning are accepted for the frontend's
    final-summary screen but NOT PERSISTED -- that needs the mapping-run /
    profile tables from models.py, which aren't wired up yet. No-ops, not
    faked behavior.
    """
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    _, target_fields = get_target_fields_for_template(db, template_id)

    result = run_pipeline(file_bytes, sheet_name, header_row, mapping, target_fields)
    output_df = result["transformed_df"]

    if skip_invalid_rows:
        output_df = output_df.drop(index=list(result["blocking_row_indices"]), errors="ignore")

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="Mapped Output")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=mapped_output.xlsx"},
    )