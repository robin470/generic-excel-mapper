"""
MVP entrypoint. No DB yet -- upload a file, get back profiled columns and
deterministic mapping suggestions; then export applies a finalized mapping
and returns a real target-shaped .xlsx. Run with:

    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/docs to try it via Swagger UI, or open
frontend/index.html directly in a browser.
"""

import json
import io

from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.excel_ingest import ingest
from app.hybrid_mapper import build_hybrid_suggestions
from app.target_schema import get_target_fields
from app.exporter import build_output_dataframe, build_output_workbook
from app.validator import validate_dataframe, summarize

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
      - deterministic mapping suggestions against the target schema
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


@app.post("/export")
async def export(
    file: UploadFile = File(...),
    sheet_name: str = Form(...),
    header_row: int = Form(...),
    mapping_json: str = Form(...),  # JSON string: [{"source_column": ..., "target_field": ...}, ...]
):
    """
    Re-reads the source file (kept stateless -- no server-side storage yet)
    and applies the finalized mapping to produce a downloadable, target-
    shaped .xlsx.
    """
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    target_fields = get_target_fields()

    output_bytes = build_output_workbook(
        file_bytes=file_bytes,
        sheet_name=sheet_name,
        header_row=header_row,
        mapping=mapping,
        target_fields=target_fields,
    )

    return StreamingResponse(
        io.BytesIO(output_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=mapped_output.xlsx"},
    )


@app.post("/validate")
async def validate(
    file: UploadFile = File(...),
    sheet_name: str = Form(...),
    header_row: int = Form(...),
    mapping_json: str = Form(...),
):
    """
    Applies the mapping (without exporting) and runs the target schema's
    validation rules, returning a summary + issue list for the review UI.
    """
    file_bytes = await file.read()
    mapping = json.loads(mapping_json)
    target_fields = get_target_fields()

    output_df = build_output_dataframe(
        file_bytes=file_bytes,
        sheet_name=sheet_name,
        header_row=header_row,
        mapping=mapping,
        target_fields=target_fields,
    )
    print("FINAL MAPPING:", mapping)
    print("OUTPUT DATAFRAME:")
    print(output_df)
    issues = validate_dataframe(output_df, target_fields)

    return {
        "row_count": len(output_df),
        **summarize(issues),
        "issues": [i.to_dict() for i in issues],
    }