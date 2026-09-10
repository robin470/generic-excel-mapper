"""
Transformation step: attempts to cast each mapped raw value into its
target field's data type. This runs BEFORE validation and is reported
as a distinct failure category ("transformation" vs "validation"),
per the requirement that a cast failure (e.g. "abc" can't become a
number) is not the same kind of problem as a business-rule failure
(e.g. a valid number that's outside an allowed range).

Only numeric/integer/decimal/date need real casting. String, email, and
boolean values pass through untouched here -- their correctness (format,
pattern, allowed values) is a validation concern, checked afterward in
validator.py.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from app.target_schema import TargetField


@dataclass
class TransformIssue:
    row_index: int
    target_field: str
    rule_violated: str
    severity: str
    stage: str
    message: str
    raw_value: str | None

    def to_dict(self):
        return asdict(self)


def _is_empty(value) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def transform_dataframe(
    df: pd.DataFrame, target_fields: list[TargetField]
) -> tuple[pd.DataFrame, list[TransformIssue]]:
    transformed = df.copy().astype(object)
    issues: list[TransformIssue] = []

    for f in target_fields:
        if f.name not in df.columns:
            continue

        for idx, raw_value in df[f.name].items():
            if _is_empty(raw_value):
                continue  # nothing to cast; required-ness is a validation concern

            if f.data_type in ("numeric", "decimal"):
                coerced = pd.to_numeric(raw_value, errors="coerce")
                if pd.isna(coerced):
                    issues.append(TransformIssue(
                        int(idx), f.name, "type_coercion_failed", "blocking", "transformation",
                        f"Could not convert '{raw_value}' to a number for '{f.name}'.",
                        str(raw_value),
                    ))
                    transformed.at[idx, f.name] = None
                else:
                    transformed.at[idx, f.name] = float(coerced)

            elif f.data_type == "integer":
                try:
                    transformed.at[idx, f.name] = int(float(raw_value))
                except (ValueError, TypeError):
                    issues.append(TransformIssue(
                        int(idx), f.name, "type_coercion_failed", "blocking", "transformation",
                        f"Could not convert '{raw_value}' to an integer for '{f.name}'.",
                        str(raw_value),
                    ))
                    transformed.at[idx, f.name] = None

            elif f.data_type == "date":
                coerced = pd.to_datetime(raw_value, errors="coerce")
                if pd.isna(coerced):
                    issues.append(TransformIssue(
                        int(idx), f.name, "type_coercion_failed", "blocking", "transformation",
                        f"Could not parse '{raw_value}' as a date for '{f.name}'.",
                        str(raw_value),
                    ))
                    transformed.at[idx, f.name] = None
                else:
                    transformed.at[idx, f.name] = coerced.to_pydatetime()

            # string / email / boolean: no casting needed at this stage

    return transformed, issues
