"""
SQLAlchemy models for template management -- the first slice of the
broader schema (see models.py for the full future picture: source
files, mapping runs, profiles, audit log). Only templates + fields are
wired to an actual DB right now.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class TemplateModel(Base):
    __tablename__ = "templates"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False)
    version = Column(Integer, default=1)
    status = Column(String(20), default="draft")  # draft | active | retired
    created_at = Column(DateTime, default=datetime.utcnow)

    fields = relationship(
        "FieldModel",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="FieldModel.order_index",
    )


class FieldModel(Base):
    __tablename__ = "template_fields"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), ForeignKey("templates.id"), nullable=False)

    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    aliases = Column(JSON, default=list)
    data_type = Column(String(20), default="string")  # string|numeric|integer|decimal|email|date|boolean
    required = Column(Boolean, default=False)
    is_primary_key = Column(Boolean, default=False)
    pattern = Column(String(500), nullable=True)
    allowed_values = Column(JSON, nullable=True)
    min_length = Column(Integer, nullable=True)
    max_length = Column(Integer, nullable=True)
    order_index = Column(Integer, default=0)

    template = relationship("TemplateModel", back_populates="fields")