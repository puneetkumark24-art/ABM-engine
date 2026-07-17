"""
models_tenant.py — the tenancy root (P0-A).

`Tenant` is the top of the isolation hierarchy. Every tenant-scoped table gets a
`tenant_id` column (added by the Postgres migration, not the ORM, so existing
code and SQLite paths are unaffected) plus Row-Level Security keyed on a session
GUC `app.current_tenant`.

BOOTSTRAP_TENANT_ID is the tenant every pre-tenancy row is backfilled into, so
the migration is non-destructive: existing data keeps working as "tenant zero".
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, JSON
from database import Base

# Fixed, well-known id so backfill + app default agree across environments.
BOOTSTRAP_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def uid() -> str:
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    slug = Column(String, unique=True)
    plan = Column(String, default="standard")
    status = Column(String, default="active")     # active/suspended
    settings = Column(JSON, default=dict)
    is_bootstrap = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
