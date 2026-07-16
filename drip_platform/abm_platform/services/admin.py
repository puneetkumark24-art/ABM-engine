"""Module 25 — Admin: users, roles, RBAC (deny-by-default), quotas.
ADM-002: permissions are additive via roles; anything not granted is denied.
ADM-003: quota exhaustion blocks the action with a clear error."""
from __future__ import annotations
from sqlalchemy.orm import Session
import models
import models_ext as mx


def create_role(db: Session, name: str, permissions: list[str]) -> mx.AppRole:
    r = mx.AppRole(name=name, permissions=permissions)
    db.add(r); db.commit()
    return r


def create_user(db: Session, email: str, name: str, role_id: str | None = None) -> mx.AppUser:
    u = mx.AppUser(email=email.lower(), name=name, role_id=role_id)
    db.add(u); db.commit()
    return u


def check_permission(db: Session, user_id: str, permission: str) -> bool:
    """ADM-002 — deny by default. Wildcards: 'crm.*' grants 'crm.read' etc."""
    u = db.get(mx.AppUser, user_id)
    if u is None or u.status != "active" or not u.role_id:
        return False
    role = db.get(mx.AppRole, u.role_id)
    if role is None:
        return False
    for p in (role.permissions or []):
        if p == permission or p == "*":
            return True
        if p.endswith(".*") and permission.startswith(p[:-1]):
            return True
    return False


def ensure_quota(db: Session, kind: str, limit: int = 1000) -> mx.Quota:
    q = db.query(mx.Quota).filter_by(kind=kind).first()
    if q is None:
        q = mx.Quota(kind=kind, limit=limit)
        db.add(q); db.commit()
    return q


def consume_quota(db: Session, kind: str, amount: int = 1) -> tuple[bool, int]:
    """Returns (allowed, remaining). ADM-003: blocks at the limit."""
    q = ensure_quota(db, kind)
    if q.used + amount > q.limit:
        return False, q.limit - q.used
    q.used += amount
    db.commit()
    return True, q.limit - q.used


def audit(db: Session, actor: str, action: str, details: str = "") -> None:
    db.add(models.AuditLog(action=action, details=details, actor=actor))
    db.commit()
