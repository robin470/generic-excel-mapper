"""
Template management API: list/create templates, add/edit/delete fields
on a draft template, publish ("Save Version") to make it active and
retire the previous active version of the same name, and clone a new
draft version from an existing one.

Fields can only be mutated while a template is in "draft" status --
once active, it's locked; changes require creating a new version first.
This keeps a template's field set immutable for any run that already
used it, without needing a separate audit log yet.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import TemplateModel, FieldModel
from app.template_service import (
    get_template_or_404,
    serialize_field,
    serialize_template_summary,
    serialize_template_detail,
)

router = APIRouter()


class TemplateCreate(BaseModel):
    name: str


class FieldIn(BaseModel):
    name: str
    description: str = ""
    aliases: list[str] = []
    data_type: str = "string"
    required: bool = False
    is_primary_key: bool = False
    pattern: str | None = None
    allowed_values: list | None = None
    min_length: int | None = None
    max_length: int | None = None


def _require_draft(template: TemplateModel):
    if template.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="This template is not a draft. Create a new version to edit its fields.",
        )


@router.get("")
def list_templates(status: str | None = None, db: Session = Depends(get_db)):
    query = db.query(TemplateModel)
    if status:
        query = query.filter(TemplateModel.status == status)
    templates = query.order_by(TemplateModel.name, TemplateModel.version).all()
    return [serialize_template_summary(t) for t in templates]


@router.post("")
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    template = TemplateModel(name=payload.name, version=1, status="draft")
    db.add(template)
    db.commit()
    db.refresh(template)
    return serialize_template_detail(template)


@router.get("/{template_id}")
def get_template(template_id: str, db: Session = Depends(get_db)):
    template = get_template_or_404(db, template_id)
    return serialize_template_detail(template)


@router.put("/{template_id}")
def rename_template(template_id: str, payload: TemplateCreate, db: Session = Depends(get_db)):
    template = get_template_or_404(db, template_id)
    _require_draft(template)
    template.name = payload.name
    db.commit()
    db.refresh(template)
    return serialize_template_detail(template)


@router.delete("/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = get_template_or_404(db, template_id)
    _require_draft(template)  # never delete an active/retired version -- it may be referenced by runs
    db.delete(template)
    db.commit()
    return {"deleted": template_id}


@router.post("/{template_id}/fields")
def add_field(template_id: str, payload: FieldIn, db: Session = Depends(get_db)):
    template = get_template_or_404(db, template_id)
    _require_draft(template)

    field = FieldModel(
        template_id=template.id,
        order_index=len(template.fields),
        **payload.model_dump(),
    )
    db.add(field)
    db.commit()
    db.refresh(template)
    return serialize_template_detail(template)


@router.put("/{template_id}/fields/{field_id}")
def update_field(template_id: str, field_id: str, payload: FieldIn, db: Session = Depends(get_db)):
    template = get_template_or_404(db, template_id)
    _require_draft(template)

    field = db.get(FieldModel, field_id)
    if not field or field.template_id != template_id:
        raise HTTPException(status_code=404, detail="Field not found on this template.")

    for key, value in payload.model_dump().items():
        setattr(field, key, value)
    db.commit()
    db.refresh(template)
    return serialize_template_detail(template)


@router.delete("/{template_id}/fields/{field_id}")
def delete_field(template_id: str, field_id: str, db: Session = Depends(get_db)):
    template = get_template_or_404(db, template_id)
    _require_draft(template)

    field = db.get(FieldModel, field_id)
    if not field or field.template_id != template_id:
        raise HTTPException(status_code=404, detail="Field not found on this template.")

    db.delete(field)
    db.commit()
    db.refresh(template)
    return serialize_template_detail(template)


@router.post("/{template_id}/publish")
def publish_template(template_id: str, db: Session = Depends(get_db)):
    """'Save Version': locks this template as the active version for its
    name, retiring whichever version was previously active."""
    template = get_template_or_404(db, template_id)
    if not template.fields:
        raise HTTPException(status_code=400, detail="Add at least one field before publishing.")

    previously_active = (
        db.query(TemplateModel)
        .filter(TemplateModel.name == template.name, TemplateModel.status == "active")
        .all()
    )
    for t in previously_active:
        t.status = "retired"

    template.status = "active"
    db.commit()
    db.refresh(template)
    return serialize_template_detail(template)


@router.post("/{template_id}/new-version")
def new_version(template_id: str, db: Session = Depends(get_db)):
    """Clones this template's fields into a fresh draft, one version higher."""
    source = get_template_or_404(db, template_id)

    latest_version = (
        db.query(TemplateModel)
        .filter(TemplateModel.name == source.name)
        .order_by(TemplateModel.version.desc())
        .first()
    )

    clone = TemplateModel(name=source.name, version=latest_version.version + 1, status="draft")
    db.add(clone)
    db.flush()

    for f in source.fields:
        db.add(FieldModel(
            template_id=clone.id,
            name=f.name,
            description=f.description,
            aliases=f.aliases,
            data_type=f.data_type,
            required=f.required,
            is_primary_key=f.is_primary_key,
            pattern=f.pattern,
            allowed_values=f.allowed_values,
            min_length=f.min_length,
            max_length=f.max_length,
            order_index=f.order_index,
        ))

    db.commit()
    db.refresh(clone)
    return serialize_template_detail(clone)