"""
property_history.py — Sprint 2: record & field history (audit CRM "no property
history" gap), built ON TOP of the Sprint-1 universal audit trail (KEEP/EXTEND —
no new capture path, we already record before/after on every mutation).
"""
from __future__ import annotations
from sqlalchemy.orm import Session
import models_audit as ma


def record_history(db: Session, table_name: str, row_id: str, limit: int = 200) -> list[dict]:
    """Full change history for one record: who/when/action/changed/before/after."""
    evs = (db.query(ma.AuditEvent)
           .filter_by(table_name=table_name, row_id=str(row_id))
           .order_by(ma.AuditEvent.at.asc()).limit(limit).all())
    return [{"at": e.at, "actor": e.actor, "action": e.action,
             "changed": e.changed, "before": e.before, "after": e.after} for e in evs]


def field_history(db: Session, table_name: str, row_id: str, field: str) -> list[dict]:
    """Timeline of one field's values across every change that touched it."""
    out = []
    for e in (db.query(ma.AuditEvent)
              .filter_by(table_name=table_name, row_id=str(row_id))
              .order_by(ma.AuditEvent.at.asc()).all()):
        if e.action == "insert" and e.after and field in e.after:
            out.append({"at": e.at, "actor": e.actor, "value": e.after[field], "from": None})
        elif e.action == "update" and (e.changed or []) and field in e.changed:
            out.append({"at": e.at, "actor": e.actor,
                        "from": (e.before or {}).get(field),
                        "value": (e.after or {}).get(field)})
    return out
