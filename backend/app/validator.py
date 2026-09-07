"""
Validation engine. Runs after mapping, before final export, per the SRS:
"Data is transformed first and validated before final export."

Pure function over a pandas DataFrame -- no DB, no I/O.
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


def validate_dataframe(df: pd.DataFrame, target_fields: list[TargetField]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # Uniqueness is a cross-row check, done as its own pass.
    for f in target_fields:
        if f.unique and f.name in df.columns:
            non_null = df[f.name].dropna()
            dup_mask = non_null.duplicated(keep=False)
            for idx in non_null.index[dup_mask]:
                issues.append(
                    ValidationIssue(
                        row_index=int(idx),
                        target_field=f.name,
                        rule_violated="unique",
                        severity="blocking",
                        message=f"Duplicate value for unique field '{f.name}'.",
                        raw_value=str(df.at[idx, f.name]),
                    )
                )

    for idx, row in df.iterrows():
        for f in target_fields:
            value = row.get(f.name)

            if _is_empty(value):
                if f.required:
                    issues.append(
                        ValidationIssue(
                            row_index=int(idx),
                            target_field=f.name,
                            rule_violated="required",
                            severity="blocking",
                            message=f"'{f.name}' is required but empty.",
                            raw_value=None,
                        )
                    )
                continue  # nothing else to check on an empty value

            str_val = str(value)

            if f.data_type in ("numeric", "decimal"):
                try:
                    float(value)
                except (ValueError, TypeError):
                    issues.append(
                        ValidationIssue(idx, f.name, "type_mismatch", "blocking",
                                         f"'{f.name}' expected a number, got '{str_val}'.", str_val)
                    )
            elif f.data_type == "integer":
                try:
                    int(float(value))
                except (ValueError, TypeError):
                    issues.append(
                        ValidationIssue(idx, f.name, "type_mismatch", "blocking",
                                         f"'{f.name}' expected an integer, got '{str_val}'.", str_val)
                    )
            elif f.data_type == "email":
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str_val):
                    issues.append(
                        ValidationIssue(idx, f.name, "email_format", "blocking",
                                         f"'{f.name}' is not a valid email: '{str_val}'.", str_val)
                    )
            elif f.data_type == "date":
                parsed = pd.to_datetime(value, errors="coerce")
                if pd.isna(parsed):
                    issues.append(
                        ValidationIssue(idx, f.name, "date_format", "blocking",
                                         f"'{f.name}' is not a recognizable date: '{str_val}'.", str_val)
                    )

            if f.pattern and f.data_type != "email":  # email already pattern-checked above
                if not re.match(f.pattern, str_val):
                    issues.append(
                        ValidationIssue(idx, f.name, "pattern", "blocking",
                                         f"'{f.name}' does not match the required pattern.", str_val)
                    )

            if f.allowed_values and value not in f.allowed_values:
                issues.append(
                    ValidationIssue(idx, f.name, "allowed_values", "warning",
                                     f"'{f.name}' value '{str_val}' is not in the allowed list.", str_val)
                )

            if f.min_length and len(str_val) < f.min_length:
                issues.append(
                    ValidationIssue(idx, f.name, "min_length", "warning",
                                     f"'{f.name}' is shorter than {f.min_length} characters.", str_val)
                )
            if f.max_length and len(str_val) > f.max_length:
                issues.append(
                    ValidationIssue(idx, f.name, "max_length", "warning",
                                     f"'{f.name}' is longer than {f.max_length} characters.", str_val)
                )

    return issues


def summarize(issues: list[ValidationIssue]) -> dict:
    blocking = [i for i in issues if i.severity == "blocking"]
    warning = [i for i in issues if i.severity == "warning"]
    return {
        "total_issues": len(issues),
        "blocking_count": len(blocking),
        "warning_count": len(warning),
    }