"""
models_audit.py — Sprint 1 (S1-03): append-only, per-tenant audit trail.

Every mutation to a business table records who/what/when with before+after
values, written automatically by the SQLAlchemy session listener in
audit_trail.py. Fixes the audit's 3/10 "audit_log is prose, not before/after,
not universal".
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Index
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36))
    actor = Column(String)                 # user/system id from request context
    request_id = Column(String)            # correlation id
    table_name = Column(String, nullable=False)
    row_id = Column(String)
    action = Column(String, nullable=False)   # insert / update / delete
    before = Column(JSON)                  # prior values (update/delete)
    after = Column(JSON)                   # new values (insert/update)
    changed = Column(JSON)                 # list of changed column names (update)
    at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_audit_table_row", "table_name", "row_id"),
                      Index("idx_audit_tenant_time", "tenant_id", "at"))


AUDIT_TABLES = [AuditEvent]
