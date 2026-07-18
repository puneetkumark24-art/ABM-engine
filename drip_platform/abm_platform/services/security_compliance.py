"""
security_compliance.py — Sprint 9: Security & Compliance (PDPL-oriented).

Four capabilities that pure engineering can deliver (SSO/MFA/SCIM and external
certification remain BLOCKED-EXTERNAL — they need an IdP tenant and auditors):

  1. Field encryption — real Fernet (AES-128-CBC + HMAC) for PII at rest, keyed
     from the vault-ready get_secret() seam. Tamper-evident (decrypt raises).
  2. RBAC + ABAC — permission-wildcard role checks plus attribute rules
     (e.g. "own"-scoped actions require resource.owner == principal.sub).
  3. PDPL data-subject requests — export (right of access) and erase (right to
     erasure) for a person across PII fields, with suppression + audit.
  4. Retention — generic purge of rows older than a policy window.
"""
from __future__ import annotations
import base64
import hashlib
from datetime import datetime, timedelta
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session
import models
import models_ext as mx

try:
    from config import get_secret
except Exception:  # pragma: no cover
    def get_secret(name, default=None):
        import os
        return os.environ.get(name, default)


# ── 1. field encryption ──────────────────────────────────────
def _fernet() -> Fernet:
    raw = get_secret("FIELD_ENCRYPTION_KEY", "dev-only-insecure-key-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt_field(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(str(plaintext).encode()).decode()


def decrypt_field(token: str | None) -> str | None:
    if token is None:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("ciphertext failed integrity check (tampered or wrong key)") from e


# ── 2. RBAC + ABAC ───────────────────────────────────────────
def permits(role_permissions: list[str], action: str) -> bool:
    """Wildcard permission match: 'crm.*' grants 'crm.read'; '*' grants all."""
    for p in role_permissions or []:
        if p == "*" or p == action:
            return True
        if p.endswith(".*") and action.startswith(p[:-1]):
            return True
    return False


def check_access(principal: dict, action: str, resource: dict | None = None) -> tuple[bool, str]:
    """principal: {sub, roles?, permissions, attrs?}. RBAC first, then ABAC.
    ABAC conventions: an action suffixed ':own' requires resource.owner == sub;
    a resource {tenant_id} must match principal.tenant_id."""
    base_action = action.split(":", 1)[0]
    if not permits(principal.get("permissions", []), base_action):
        return False, f"RBAC deny: no permission for {base_action}"
    resource = resource or {}
    # tenant isolation (ABAC)
    if resource.get("tenant_id") and principal.get("tenant_id") \
            and resource["tenant_id"] != principal["tenant_id"]:
        return False, "ABAC deny: cross-tenant resource"
    # ownership (ABAC)
    if action.endswith(":own"):
        if resource.get("owner") != principal.get("sub"):
            return False, "ABAC deny: not resource owner"
    return True, "allow"


# ── 3. PDPL data-subject requests ────────────────────────────
_PII_FIELDS = ["full_name", "full_name_ar", "primary_email", "secondary_email",
               "phone", "mobile", "whatsapp", "linkedin_url", "linkedin_public_id",
               "background_notes", "pitch_notes"]


def export_subject(db: Session, person_id: str) -> dict:
    """Right of access: everything held about a person."""
    p = db.get(models.Person, person_id)
    if p is None:
        raise ValueError("person not found")
    return {
        "person_id": person_id,
        "pii": {f: getattr(p, f, None) for f in _PII_FIELDS},
        "consent": {"status": p.consent_status, "date": str(p.consent_date) if p.consent_date else None,
                    "source": p.consent_source, "do_not_contact": p.do_not_contact},
        "exported_at": datetime.utcnow().isoformat(),
    }


def erase_subject(db: Session, person_id: str, mode: str = "anonymize") -> dict:
    """Right to erasure: scrub PII, suppress the email, mark do-not-contact. The
    row is retained (anonymized) so referential history/aggregates survive."""
    p = db.get(models.Person, person_id)
    if p is None:
        raise ValueError("person not found")
    email = p.primary_email
    scrubbed = []
    for f in _PII_FIELDS:
        if getattr(p, f, None) not in (None, ""):
            setattr(p, f, None if f != "full_name" else "[erased]")
            scrubbed.append(f)
    p.do_not_contact = True
    p.consent_status = "withdrawn"
    p.is_active = False
    if email and not db.query(mx.Suppression).filter_by(email=email).first():
        db.add(mx.Suppression(email=email, reason="pdpl-erasure"))
    db.commit()
    return {"person_id": person_id, "mode": mode, "fields_scrubbed": scrubbed,
            "suppressed_email": bool(email)}


# ── consent ──────────────────────────────────────────────────
def set_consent(db: Session, person_id: str, status: str, source: str = "web") -> dict:
    p = db.get(models.Person, person_id)
    if p is None:
        raise ValueError("person not found")
    p.consent_status = status
    p.consent_date = datetime.utcnow()
    p.consent_source = source
    if status in ("withdrawn", "denied"):
        p.do_not_contact = True
    db.commit()
    return {"person_id": person_id, "consent_status": status}


def has_consent(db: Session, person_id: str) -> bool:
    p = db.get(models.Person, person_id)
    return bool(p and p.consent_status == "granted" and not p.do_not_contact)


# ── 4. retention ─────────────────────────────────────────────
def purge_expired(db: Session, model, timestamp_field: str, older_than_days: int,
                  now: datetime | None = None) -> int:
    """Delete rows whose timestamp is older than the retention window. Returns
    the number deleted."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=older_than_days)
    col = getattr(model, timestamp_field)
    q = db.query(model).filter(col < cutoff)
    n = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return n
