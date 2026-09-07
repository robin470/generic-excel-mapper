"""
Excel ingestion + profiling. No DB, no persistence -- everything is
computed in-memory from the uploaded bytes and returned to the caller.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, asdict

import pandas as pd


@dataclass
class ColumnProfile:
    name: str
    column_index: int
    inferred_type: str
    sample_values: list
    null_rate: float

    def to_dict(self):
        return asdict(self)


def list_sheet_names(file_bytes: bytes) -> list[str]:
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    return xl.sheet_names


def _looks_like_header_row(row: pd.Series) -> bool:
    """Heuristic: a header row is mostly non-null strings, no duplicates."""
    non_null = row.dropna()
    # A real header should have at least 2 populated cells.
    if len(non_null) < 2:
        return False
    str_ratio = sum(isinstance(v, str) for v in non_null) / len(non_null)
    unique_ratio = len(set(non_null)) / len(non_null)
    return str_ratio > 0.7 and unique_ratio > 0.9


def detect_header_row(file_bytes: bytes, sheet_name: str, max_scan_rows: int = 10) -> int:
    """Scan the first few rows and return the index most likely to be the header."""
    raw = pd.read_excel(
        io.BytesIO(file_bytes), sheet_name=sheet_name, header=None, nrows=max_scan_rows
    )
    candidates = []

    for i in range(len(raw)):
        if _looks_like_header_row(raw.iloc[i]):
            non_null_count = raw.iloc[i].notna().sum()
            candidates.append((i, non_null_count))

    if candidates:
        # Prefer the candidate with the most populated cells.
        return max(candidates, key=lambda x: x[1])[0]

    return 0  # fall back to first row


def _infer_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "unknown"
    if pd.api.types.is_bool_dtype(non_null):
        return "boolean"
    if pd.api.types.is_integer_dtype(non_null):
        return "integer"
    if pd.api.types.is_float_dtype(non_null):
        return "decimal"
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return "date"
    # try coercing strings to see if they're secretly numeric/date columns
    coerced_numeric = pd.to_numeric(non_null, errors="coerce")
    if coerced_numeric.notna().mean() > 0.9:
        return "numeric"
    coerced_date = pd.to_datetime(non_null, errors="coerce")
    if coerced_date.notna().mean() > 0.9:
        return "date"
    return "string"


def profile_sheet(file_bytes: bytes, sheet_name: str, header_row: int) -> tuple[pd.DataFrame, list[ColumnProfile]]:
    """Read the sheet with the given header row and profile every column."""
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    profiles: list[ColumnProfile] = []
    for idx, col in enumerate(df.columns):
        series = df[col]
        sample = series.dropna().astype(str).head(5).tolist()
        null_rate = float(series.isna().mean()) if len(series) else 0.0
        profiles.append(
            ColumnProfile(
                name=col,
                column_index=idx,
                inferred_type=_infer_type(series),
                sample_values=sample,
                null_rate=round(null_rate, 4),
            )
        )
    return df, profiles


def ingest(file_bytes: bytes, sheet_name: str | None = None) -> dict:
    """Full ingestion entrypoint: pick sheet, detect header, profile columns."""
    sheets = list_sheet_names(file_bytes)
    chosen_sheet = sheet_name or sheets[0]
    header_row = detect_header_row(file_bytes, chosen_sheet)
    df, profiles = profile_sheet(file_bytes, chosen_sheet, header_row)

    return {
        "available_sheets": sheets,
        "chosen_sheet": chosen_sheet,
        "header_row_index": header_row,
        "row_count": len(df),
        "columns": [p.to_dict() for p in profiles],
    }
