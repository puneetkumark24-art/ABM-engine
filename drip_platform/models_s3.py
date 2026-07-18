"""
models_s3.py — Sprint 3 (Marketing Automation): journey orchestration.

Two additive tables (no existing table touched). A JourneyDef stores the whole
node graph as JSON (send / wait / branch / exit nodes); a JourneyEnrollment
tracks one person walking that graph with a scheduled next_action_at and a
history trail. Tenant-scoped (RLS GUC + tenant_id) like every business table.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, JSON, Index
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class JourneyDef(Base):
    __tablename__ = "journey_defs"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    name = Column(String(200), nullable=False)
    nodes = Column(JSON, nullable=False, default=list)   # [{id,type,...}]
    entry_node_id = Column(String(64), nullable=False)
    status = Column(String(20), default="active")        # active | paused | archived
    created_at = Column(DateTime, default=datetime.utcnow)


class JourneyEnrollment(Base):
    __tablename__ = "journey_enrollments"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    journey_id = Column(String(36), index=True, nullable=False)
    person_id = Column(String(36), index=True)
    current_node_id = Column(String(64))
    status = Column(String(20), default="active")        # active | completed | exited
    next_action_at = Column(DateTime, index=True)
    history = Column(JSON, default=list)
    enrolled_at = Column(DateTime, default=datetime.utcnow)


Index("ix_journey_enr_due", JourneyEnrollment.status, JourneyEnrollment.next_action_at)

S3_TABLES = ["journey_defs", "journey_enrollments"]
