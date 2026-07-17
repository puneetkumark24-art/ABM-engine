"""
models_p12.py — Phase 12 tables: CRM configurability layer (custom properties,
saved views, tasks) — the HubSpot capabilities the honest scorecard flagged.
New file, purely additive.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    JSON, UniqueConstraint, Index
)
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


class PropertyDef(Base):
    """Custom property definition (HubSpot 'properties'). object_type: person /
    organization / opportunity. Supports default values (HubSpot 2026 feature)."""
    __tablename__ = "property_defs"
    id = Column(String(36), primary_key=True, default=uid)
    object_type = Column(String, nullable=False)
    key = Column(String, nullable=False)                  # snake_case, immutable once data exists
    label = Column(String, nullable=False)
    data_type = Column(String, default="text")            # text/number/date/bool/enum
    options = Column(JSON, default=list)                  # for enum
    default_value = Column(String)                        # applied when record has no value
    required = Column(Boolean, default=False)
    group = Column(String, default="custom")
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("object_type", "key"),)


class PropertyValue(Base):
    """EAV value store for custom properties."""
    __tablename__ = "property_values"
    id = Column(String(36), primary_key=True, default=uid)
    property_id = Column(String(36), ForeignKey("property_defs.id"), nullable=False)
    object_type = Column(String, nullable=False)
    object_id = Column(String(36), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("property_id", "object_id"),
                      Index("idx_pv_object", "object_type", "object_id"))


class SavedView(Base):
    """Saved filtered view over an object type (HubSpot views/lists). Filters
    may reference native columns, custom properties (custom.<key>) and the
    engagement pseudo-field (engagement_score)."""
    __tablename__ = "saved_views"
    id = Column(String(36), primary_key=True, default=uid)
    object_type = Column(String, nullable=False)          # person / organization / opportunity
    name = Column(String, nullable=False, unique=True)
    filters = Column(JSON, default=list)                  # [{field, op, value}]
    sort_by = Column(String)
    sort_desc = Column(Boolean, default=True)
    owner = Column(String, default="Puneet")
    created_at = Column(DateTime, default=datetime.utcnow)


class CrmTask(Base):
    """Real task object (HubSpot tasks + 2026 subtasks): due dates, assignee,
    priority, reminders, related record, parent for subtasks."""
    __tablename__ = "crm_tasks"
    id = Column(String(36), primary_key=True, default=uid)
    title = Column(String, nullable=False)
    notes = Column(Text)
    due_at = Column(DateTime)
    reminder_at = Column(DateTime)
    assignee = Column(String, default="Puneet")
    priority = Column(String, default="med")              # low/med/high
    status = Column(String, default="open")               # open/done/skipped
    related_type = Column(String)                         # person/organization/opportunity
    related_id = Column(String(36))
    parent_task_id = Column(String(36), ForeignKey("crm_tasks.id"), nullable=True)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_task_assignee", "assignee", "status"),
                      Index("idx_task_related", "related_type", "related_id"),)


PHASE12_TABLES = [PropertyDef, PropertyValue, SavedView, CrmTask]
