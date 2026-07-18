"""
models_segments.py — Parity Mission: dynamic segments + static lists
(Mailchimp segments / HubSpot active+static lists gap).
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Boolean, UniqueConstraint
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class SegmentDef(Base):
    __tablename__ = "segment_defs"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    name = Column(String(150), nullable=False)
    entity = Column(String(20), default="persons")
    # [{field, op, value}] AND-combined; op ∈ eq|neq|contains|gt|lt|in|exists
    conditions = Column(JSON, default=list)
    is_dynamic = Column(Boolean, default=True)   # dynamic = evaluated live
    created_at = Column(DateTime, default=datetime.utcnow)


class ListMembership(Base):
    """Static list membership (list = a SegmentDef with is_dynamic=False)."""
    __tablename__ = "list_memberships"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    segment_id = Column(String(36), index=True, nullable=False)
    person_id = Column(String(36), index=True, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("segment_id", "person_id", name="uq_list_member"),)


SEGMENT_TABLES = ["segment_defs", "list_memberships"]
