"""
Validation engine. Runs on the TRANSFORMED dataframe (see transformer.py),
after casting -- this only checks business rules on values that are
already the right type: required, pattern, allowed values, length,
uniqueness. Type/format casting failures are a transformer concern, not
this module's, so they aren't duplicated here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

import pandas as pd

from app.target_schema import TargetField


@dataclass
class ValidationIssue:
    row_index: int
    target_field: str
    rule_violated: str
    severity: str  # "blocking" | "warning"
    stage: str  # "validation" (this module) | "transformation" (transformer.py)
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


def validate_dataframe(
    df: pd.DataFrame,
    target_fields: list[TargetField],
    skip_required_cells: set[tuple[int, str]] = frozenset(),
) -> list[ValidationIssue]:
    """
    skip_required_cells: (row_index, field_name) pairs that already have a
    transformation failure recorded -- we don't also flag them as
    "required but empty" just because the failed cast left them null.
    """
    issues: list[ValidationIssue] = []

    # Uniqueness is a cross-row check, done as its own pass.
    for f in target_fields:
        if f.unique and f.name in df.columns:
            non_null = df[f.name].dropna()
            dup_mask = non_null.duplicated(keep=False)
            for idx in non_null.index[dup_mask]:
                issues.append(ValidationIssue(
                    int(idx), f.name, "unique", "blocking", "validation",
                    f"Duplicate value for unique field '{f.name}'.",
                    str(df.at[idx, f.name]),
                ))

    for idx, row in df.iterrows():
        for f in target_fields:
            value = row.get(f.name)

            if _is_empty(value):
                if f.required and (int(idx), f.name) not in skip_required_cells:
                    issues.append(ValidationIssue(
                        int(idx), f.name, "required", "blocking", "validation",
                        f"'{f.name}' is required but empty.", None,
                    ))
                continue

            str_val = str(value)

            if f.data_type == "email":
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str_val):
                    issues.append(ValidationIssue(
                        int(idx), f.name, "email_format", "blocking", "validation",
                        f"'{f.name}' is not a valid email: '{str_val}'.", str_val,
                    ))

            if f.pattern and f.data_type != "email":
                if not re.match(f.pattern, str_val):
                    issues.append(ValidationIssue(
                        int(idx), f.name, "pattern", "blocking", "validation",
                        f"'{f.name}' does not match the required pattern.", str_val,
                    ))

            if f.allowed_values and value not in f.allowed_values:
                issues.append(ValidationIssue(
                    int(idx), f.name, "allowed_values", "warning", "validation",
                    f"'{f.name}' value '{str_val}' is not in the allowed list.", str_val,
                ))

            if f.min_length and len(str_val) < f.min_length:
                issues.append(ValidationIssue(
                    int(idx), f.name, "min_length", "warning", "validation",
                    f"'{f.name}' is shorter than {f.min_length} characters.", str_val,
                ))
            if f.max_length and len(str_val) > f.max_length:
                issues.append(ValidationIssue(
                    int(idx), f.name, "max_length", "warning", "validation",
                    f"'{f.name}' is longer than {f.max_length} characters.", str_val,
                ))

    return issues


def summarize(issues: list) -> dict:
    blocking = [i for i in issues if i.severity == "blocking"]
    warning = [i for i in issues if i.severity == "warning"]
    transformation = [i for i in issues if i.stage == "transformation"]
    validation = [i for i in issues if i.stage == "validation"]
    return {
        "total_issues": len(issues),
        "blocking_count": len(blocking),
        "warning_count": len(warning),
        "transformation_error_count": len(transformation),
        "validation_error_count": len(validation),
    }
