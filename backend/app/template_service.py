"""
Glue between the DB (db_models.py) and the rest of the pipeline, which
only knows about the plain TargetField dataclass (target_schema.py).
Keeping this conversion in one place means the mapper/transformer/
validator/exporter never need to know templates come from a database.
"""

from __future__ import annotations

from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.db_models import TemplateModel, FieldModel
from app.target_schema import TargetField, SEED_TARGET_FIELDS


def field_model_to_target_field(f: FieldModel) -> TargetField:
    return TargetField(
        name=f.name,
        description=f.description or "",
        aliases=f.aliases or [],
        data_type=f.data_type,
        required=f.required,
        unique=f.is_primary_key,
        pattern=f.pattern,
        allowed_values=f.allowed_values,
        min_length=f.min_length,
        max_length=f.max_length,
    )


def get_template_or_404(db: Session, template_id: str) -> TemplateModel:
    template = db.get(TemplateModel, template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return template


def get_default_active_template(db: Session) -> TemplateModel:
    template = (
        db.query(TemplateModel)
        .filter(TemplateModel.status == "active")
        .order_by(TemplateModel.created_at.desc())
        .first()
    )
    if not template:
        raise HTTPException(
            status_code=400,
            detail="No active template exists. Create and publish a template first.",
        )
    return template


def get_target_fields_for_template(db: Session, template_id: str | None) -> tuple[TemplateModel, list[TargetField]]:
    template = get_template_or_404(db, template_id) if template_id else get_default_active_template(db)
    return template, [field_model_to_target_field(f) for f in template.fields]


def serialize_field(f: FieldModel) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "description": f.description,
        "aliases": f.aliases or [],
        "data_type": f.data_type,
        "required": f.required,
        "is_primary_key": f.is_primary_key,
        "pattern": f.pattern,
        "allowed_values": f.allowed_values,
        "min_length": f.min_length,
        "max_length": f.max_length,
    }


def serialize_template_summary(t: TemplateModel) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "version": t.version,
        "status": t.status,
        "field_count": len(t.fields),
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def serialize_template_detail(t: TemplateModel) -> dict:
    return {
        **serialize_template_summary(t),
        "fields": [serialize_field(f) for f in t.fields],
    }


def seed_default_template(db: Session) -> None:
    """Only runs once -- if any template already exists, do nothing."""
    if db.query(TemplateModel).first():
        return

    template = TemplateModel(name="Default Customer Template", version=1, status="active")
    db.add(template)
    db.flush()  # get template.id

    for idx, sf in enumerate(SEED_TARGET_FIELDS):
        db.add(FieldModel(
            template_id=template.id,
            name=sf.name,
            description=sf.description,
            aliases=sf.aliases,
            data_type=sf.data_type,
            required=sf.required,
            is_primary_key=sf.unique,
            pattern=sf.pattern,
            allowed_values=sf.allowed_values,
            min_length=sf.min_length,
            max_length=sf.max_length,
            order_index=idx,
        ))
    db.commit()