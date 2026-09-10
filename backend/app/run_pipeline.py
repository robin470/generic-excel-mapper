"""
Shared pipeline: raw mapped data -> transform -> validate.
Used by /validate, /validate/report, and /export so all three always
agree on what "valid" means -- no drift between the review screen and
what actually gets exported.
"""

from __future__ import annotations

import pandas as pd

from app.target_schema import TargetField
from app.exporter import build_output_dataframe
from app.transformer import transform_dataframe
from app.validator import validate_dataframe, summarize


def run_pipeline(
    file_bytes: bytes,
    sheet_name: str,
    header_row: int,
    mapping: list[dict],
    target_fields: list[TargetField],
) -> dict:
    raw_df = build_output_dataframe(file_bytes, sheet_name, header_row, mapping, target_fields)
    transformed_df, transform_issues = transform_dataframe(raw_df, target_fields)

    failed_cells = {(i.row_index, i.target_field) for i in transform_issues}
    validation_issues = validate_dataframe(transformed_df, target_fields, skip_required_cells=failed_cells)

    all_issues = transform_issues + validation_issues
    blocking_row_indices = {i.row_index for i in all_issues if i.severity == "blocking"}

    return {
        "transformed_df": transformed_df,
        "issues": all_issues,
        "summary": {
            "row_count": len(transformed_df),
            "valid_row_count": len(transformed_df) - len(blocking_row_indices),
            **summarize(all_issues),
        },
        "blocking_row_indices": blocking_row_indices,
    }
