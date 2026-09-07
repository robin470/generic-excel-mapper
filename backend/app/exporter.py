"""
Builds the standardized output workbook from the source file + finalized
column mapping. No DB -- the caller re-sends the source file bytes along
with the mapping decisions, so this stays completely stateless.
"""

from __future__ import annotations

import io

import pandas as pd

from app.target_schema import TargetField


def build_output_dataframe(
    file_bytes: bytes,
    sheet_name: str,
    header_row: int,
    mapping: list[dict],  # [{"source_column": str | None, "target_field": str}, ...]
    target_fields: list[TargetField],
) -> pd.DataFrame:
    """
    mapping should cover every target field the user wants populated:
    {"source_column": "Cust ID", "target_field": "customer_id"}
    A target field with source_column None is left empty in the output
    (useful for optional fields nobody mapped).

    Shared by both /export (write to xlsx) and /validate (check rules)
    so the two never drift apart on how the mapping is applied.
    """
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    target_order = [tf.name for tf in target_fields]
    output = pd.DataFrame(index=df.index, columns=target_order)

    source_by_target = {m["target_field"]: m.get("source_column") for m in mapping}

    for tf_name in target_order:
        src_col = source_by_target.get(tf_name)
        if src_col and src_col in df.columns:
            output[tf_name] = df[src_col]
        else:
            output[tf_name] = None

    return output


def build_output_workbook(
    file_bytes: bytes,
    sheet_name: str,
    header_row: int,
    mapping: list[dict],
    target_fields: list[TargetField],
) -> bytes:
    output = build_output_dataframe(file_bytes, sheet_name, header_row, mapping, target_fields)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        output.to_excel(writer, index=False, sheet_name="Mapped Output")
    buffer.seek(0)
    return buffer.read()