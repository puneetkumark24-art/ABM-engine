"""
audit_trail.py — Sprint 1 (S1-03): the universal audit listener.

Registering this module (import it once at app/worker boot) attaches a
SQLAlchemy `before_flush` listener that, for every INSERT/UPDATE/DELETE on a
whitelisted business table, records an append-only AuditEvent with before/after
values, the actor, tenant, and request-id from context. High-volume event/job
tables are excluded to avoid audit amplification.

Actor + tenant come from contextvars set by the auth middleware; falls back to
'system' for worker-initiated changes.
"""
from __future__ import annotations
import logging
from datetime import datetime, date
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
import models_audit as ma

logger = logging.getLogger("drip.audit")

# Business tables worth auditing. Exclude high-volume event/job/audit tables.
AUDITED_TABLES = {
    "organizations", "account_intelligence", "persons", "opportunities",
    "buying_committee_members", "product_fit", "drafts", "templates",
    "sequence_definitions", "sequence_enrollments", "email_campaigns",
    "audiences", "suppressions", "rules", "workflow_defs", "app_users",
    "app_roles", "quotas", "pipelines", "pipeline_stages",
    "opportunity_stage_links", "form_defs", "landing_pages", "assets",
    "property_defs", "property_values", "saved_views", "crm_tasks",
}


def _ctx():
    """(actor, tenant_id, request_id) from request context, best-effort."""
    actor = tenant = rid = None
    try:
        from database import current_tenant_var
        tenant = current_tenant_var.get()
    except Exception:
        pass
    try:
        from observability import request_id_var
        rid = request_id_var.get()
    except Exception:
        pass
    return (actor or "system"), tenant, rid


def _serialize(obj) -> dict:
    out = {}
    for col in inspect(obj).mapper.column_attrs:
        v = getattr(obj, col.key, None)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        elif not isinstance(v, (str, int, float, bool, type(None), list, dict)):
            v = str(v)
        out[col.key] = v
    return out


def _row_id(obj):
    pk = inspect(obj).identity
    return str(pk[0]) if pk else getattr(obj, "id", None)


def _before_flush(session: Session, flush_context, instances):
    actor, tenant, rid = _ctx()
    events = []

    import uuid as _uuid
    for obj in session.new:
        tbl = getattr(obj, "__tablename__", None)
        if tbl in AUDITED_TABLES:
            # the Python-side id default hasn't run yet in before_flush; assign it
            # now so the audit row_id matches the row that will be inserted.
            rid_val = getattr(obj, "id", None)
            if rid_val is None and hasattr(obj, "id"):
                rid_val = str(_uuid.uuid4())
                obj.id = rid_val
            events.append(ma.AuditEvent(tenant_id=tenant, actor=actor, request_id=rid,
                                        table_name=tbl, row_id=rid_val,
                                        action="insert", after=_serialize(obj)))
    for obj in session.dirty:
        tbl = getattr(obj, "__tablename__", None)
        if tbl not in AUDITED_TABLES:
            continue
        state = inspect(obj)
        before, after, changed = {}, {}, []
        for attr in state.mapper.column_attrs:
            hist = state.attrs[attr.key].history
            if hist.has_changes():
                old = hist.deleted[0] if hist.deleted else None
                new = hist.added[0] if hist.added else getattr(obj, attr.key, None)
                before[attr.key] = old.isoformat() if isinstance(old, (datetime, date)) else old
                after[attr.key] = new.isoformat() if isinstance(new, (datetime, date)) else new
                changed.append(attr.key)
        if changed:
            events.append(ma.AuditEvent(tenant_id=tenant, actor=actor, request_id=rid,
                                        table_name=tbl, row_id=_row_id(obj),
                                        action="update", before=before, after=after,
                                        changed=changed))
    for obj in session.deleted:
        tbl = getattr(obj, "__tablename__", None)
        if tbl in AUDITED_TABLES:
            events.append(ma.AuditEvent(tenant_id=tenant, actor=actor, request_id=rid,
                                        table_name=tbl, row_id=_row_id(obj),
                                        action="delete", before=_serialize(obj)))

    for e in events:
        session.add(e)


_REGISTERED = False


def register():
    """Attach the listener once. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "before_flush", _before_flush)
    _REGISTERED = True
    logger.info("audit trail listener registered for %d tables", len(AUDITED_TABLES))
