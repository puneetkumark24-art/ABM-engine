"""
models_final.py — Final wave: meetings (biggest remaining CRM gap) and
preference profiles (Mailchimp preference-center gap). Additive, tenant-scoped.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Text, Index, UniqueConstraint
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    title = Column(String(200), nullable=False)
    org_id = Column(String(36), index=True)
    person_id = Column(String(36), index=True)
    owner = Column(String(120))                    # rep responsible
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime)
    location = Column(String(300))                 # room / video link
    agenda = Column(Text)
    status = Column(String(20), default="scheduled")  # scheduled|completed|cancelled|no_show
    outcome_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_meetings_upcoming", "status", "starts_at"),)


class PreferenceProfile(Base):
    """Per-person communication preferences (public preference center)."""
    __tablename__ = "preference_profiles"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    person_id = Column(String(36), nullable=False)
    # {"product_updates": true, "events": false, "insights": true}
    categories = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("person_id", name="uq_pref_person"),)


FINAL_TABLES = ["meetings", "preference_profiles"]
