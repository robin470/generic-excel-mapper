"""
Generic Excel Mapper - Core Data Models (SQLAlchemy 2.0 style)

Drop this into app/models.py in your FastAPI project.
Uses SQLite-friendly types (JSON as Text via SQLAlchemy JSON type works fine
on SQLite too) so you can start with `sqlite:///./mapper.db` and swap the
engine URL to Postgres later with zero model changes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DataType(str, enum.Enum):
    STRING = "string"
    NUMERIC = "numeric"
    DECIMAL = "decimal"
    INTEGER = "integer"
    EMAIL = "email"
    DATE = "date"
    BOOLEAN = "boolean"


class MappingMethod(str, enum.Enum):
    DETERMINISTIC = "deterministic"
    AI = "ai"
    MANUAL = "manual"
    PROFILE = "profile"  # pulled in from a reused mapping profile


class MappingStatus(str, enum.Enum):
    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    OVERRIDDEN = "overridden"
    UNRESOLVED = "unresolved"


class TemplateStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class RunStatus(str, enum.Enum):
    PROFILING = "profiling"
    MAPPING = "mapping"
    REVIEW = "review"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity(str, enum.Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


# ---------------------------------------------------------------------------
# Target template + validation schema
# ---------------------------------------------------------------------------

class TargetTemplate(Base):
    __tablename__ = "target_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[TemplateStatus] = mapped_column(
        Enum(TemplateStatus), default=TemplateStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    fields: Mapped[list["TargetField"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TargetField(Base):
    """A single column in the target template. Doubles as the validation rule."""

    __tablename__ = "target_fields"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("target_templates.id"))

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)  # synonyms for matching

    data_type: Mapped[DataType] = mapped_column(Enum(DataType), default=DataType.STRING)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    unique: Mapped[bool] = mapped_column(Boolean, default=False)

    min_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)  # regex
    allowed_values: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # simple cross-field rule, e.g. {"if": "country == 'US'", "then": "state required"}
    conditional_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    order_index: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped[TargetTemplate] = relationship(back_populates="fields")


# ---------------------------------------------------------------------------
# Source file / sheet / column profiling
# ---------------------------------------------------------------------------

class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    client_name: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sheets: Mapped[list["SourceSheet"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class SourceSheet(Base):
    __tablename__ = "source_sheets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    file_id: Mapped[str] = mapped_column(ForeignKey("source_files.id"))
    sheet_name: Mapped[str] = mapped_column(String(200))
    header_row_index: Mapped[int] = mapped_column(Integer, default=0)
    data_row_count: Mapped[int] = mapped_column(Integer, default=0)

    file: Mapped[SourceFile] = relationship(back_populates="sheets")
    columns: Mapped[list["SourceColumn"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan"
    )


class SourceColumn(Base):
    __tablename__ = "source_columns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    sheet_id: Mapped[str] = mapped_column(ForeignKey("source_sheets.id"))

    name: Mapped[str] = mapped_column(String(300))
    column_index: Mapped[int] = mapped_column(Integer)
    inferred_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sample_values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    null_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    sheet: Mapped[SourceSheet] = relationship(back_populates="columns")


# ---------------------------------------------------------------------------
# Mapping profiles (reusable), runs, and per-column mapping decisions
# ---------------------------------------------------------------------------

class MappingProfile(Base):
    """A saved, reusable source-shape -> target-template mapping for a client."""

    __tablename__ = "mapping_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    client_name: Mapped[str] = mapped_column(String(200))
    template_id: Mapped[str] = mapped_column(ForeignKey("target_templates.id"))
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/approved
    # fingerprint of sorted source column names, used for structural-similarity lookup
    structural_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # {source_column_name: target_field_name}
    mapping_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("client_name", "name", "version"),)


class MappingRun(Base):
    __tablename__ = "mapping_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_file_id: Mapped[str] = mapped_column(ForeignKey("source_files.id"))
    sheet_id: Mapped[str] = mapped_column(ForeignKey("source_sheets.id"))
    template_id: Mapped[str] = mapped_column(ForeignKey("target_templates.id"))
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("mapping_profiles.id"), nullable=True
    )

    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.PROFILING)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    column_mappings: Mapped[list["ColumnMapping"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ColumnMapping(Base):
    """One source-column -> target-field decision within a run."""

    __tablename__ = "column_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("mapping_runs.id"))
    source_column_id: Mapped[str] = mapped_column(ForeignKey("source_columns.id"))
    target_field_id: Mapped[str | None] = mapped_column(
        ForeignKey("target_fields.id"), nullable=True
    )  # nullable: can be unresolved / unmapped

    method: Mapped[MappingMethod] = mapped_column(Enum(MappingMethod))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    # alternative candidates the AI considered, for the review UI
    alternatives: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[MappingStatus] = mapped_column(
        Enum(MappingStatus), default=MappingStatus.PENDING_REVIEW
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    run: Mapped[MappingRun] = relationship(back_populates="column_mappings")
    audit_entries: Mapped[list["AuditLog"]] = relationship(
        back_populates="mapping", cascade="all, delete-orphan"
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    mapping_id: Mapped[str] = mapped_column(ForeignKey("column_mappings.id"))
    changed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    old_target_field_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    new_target_field_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    mapping: Mapped[ColumnMapping] = relationship(back_populates="audit_entries")


# ---------------------------------------------------------------------------
# Validation results
# ---------------------------------------------------------------------------

class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("mapping_runs.id"))
    row_index: Mapped[int] = mapped_column(Integer)
    target_field_id: Mapped[str | None] = mapped_column(
        ForeignKey("target_fields.id"), nullable=True
    )
    rule_violated: Mapped[str] = mapped_column(String(100))  # e.g. "required", "pattern"
    severity: Mapped[Severity] = mapped_column(Enum(Severity), default=Severity.BLOCKING)
    message: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[MappingRun] = relationship(back_populates="validation_issues")
