"""
tenancy.py — tenant context plumbing (P0-A).

The application connects to Postgres as a NON-superuser role (`app_rw`) so that
Row-Level Security actually applies (superusers bypass RLS). Every request opens
a session and sets `SET LOCAL app.current_tenant = '<tenant_id>'`; RLS policies
then transparently scope every query to that tenant. No query in the codebase
needs a manual `WHERE tenant_id = ...` — the database enforces it.

Provides:
  set_tenant(session, tenant_id)      set the GUC on an open session
  tenant_session(tenant_id)           context manager -> a scoped Session
  get_tenant_db (FastAPI dependency)  scoped session from the request principal
"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import SessionLocal


def set_tenant(session: Session, tenant_id: str) -> None:
    """Set the RLS GUC for this transaction. Parameterized to avoid injection."""
    session.execute(text("SELECT set_config('app.current_tenant', :tid, true)"),
                    {"tid": str(tenant_id)})


@contextmanager
def tenant_session(tenant_id: str):
    db = SessionLocal()
    try:
        set_tenant(db, tenant_id)
        yield db
    finally:
        db.close()


# ── FastAPI dependency ───────────────────────────────────────
def get_tenant_db(tenant_id: Optional[str] = None):
    """Dependency factory. In routes, combine with the auth principal:
        def route(db = Depends(get_tenant_db), principal = Depends(current_principal)):
    In practice `current_principal` injects tenant_id; here we accept it directly
    for services/tests. If tenant_id is None the session is unscoped (GUC unset)
    — used only by system/admin paths and by the gradual-rollout permissive
    policy.
    """
    db = SessionLocal()
    try:
        if tenant_id:
            set_tenant(db, tenant_id)
        yield db
    finally:
        db.close()
