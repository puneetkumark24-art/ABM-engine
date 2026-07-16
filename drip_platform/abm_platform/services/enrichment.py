"""Module 03 — Enrichment Engine: waterfall enrichment, email verification,
duplicate detection. Providers are pluggable callables; none are external by
default (register real Apollo/Clay adapters later behind the same interface).
ENR-002: never overwrite a confirmed field with an unconfirmed value."""
from __future__ import annotations
import re
from datetime import datetime
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
import models
import models_ext as mx

# provider registry: name -> callable(person) -> dict of found fields
_PROVIDERS: list[tuple[str, callable]] = []


def register_provider(name: str, fn) -> None:
    _PROVIDERS.append((name, fn))


def clear_providers() -> None:
    _PROVIDERS.clear()


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def verify_email(email: str | None) -> str:
    """Offline verification: syntax check. Returns Confirmed-syntax/Invalid/Unknown.
    (MX/SMTP probing is a deliberate later add — needs network + care.)"""
    if not email:
        return "Unknown"
    return "Valid-syntax" if EMAIL_RE.match(email.strip()) else "Invalid"


def run_waterfall(db: Session, person_id: str, required: list[str] | None = None) -> mx.EnrichmentJob:
    """Try providers in priority order until required fields are filled.
    ENR-001: stop at first provider that satisfies requirements (cost control).
    ENR-002: a field already present + email_confidence Confirmed is never overwritten."""
    required = required or ["primary_email", "current_title"]
    person = db.get(models.Person, person_id)
    job = mx.EnrichmentJob(entity_type="person", entity_id=person_id, status="running")
    db.add(job); db.flush()

    found: dict = {}
    tried: list[str] = []
    for name, fn in _PROVIDERS:
        tried.append(name)
        try:
            data = fn(person) or {}
        except Exception as e:
            data = {}
            found.setdefault("_errors", []).append(f"{name}: {e}")
        for k, v in data.items():
            if not v or k.startswith("_"):
                continue
            current = getattr(person, k, None)
            confirmed = (person.email_confidence or "").lower() == "confirmed"
            if k == "primary_email" and current and confirmed:
                continue  # ENR-002
            if current in (None, "", "Unknown") or k == "primary_email" and not confirmed:
                setattr(person, k, v)
                found[k] = v
        if all(getattr(person, f, None) for f in required):
            break

    # verify email after enrichment
    status = verify_email(person.primary_email)
    if status == "Invalid":
        person.do_not_contact = True   # ENR-003: invalid email is not contactable by email
        found["_email_invalid"] = True
    if status == "Valid-syntax" and (person.email_confidence or "Unknown") == "Unknown":
        person.email_confidence = "Valid-syntax"

    job.providers_tried = tried
    job.result = found
    job.status = "done" if all(getattr(person, f, None) for f in required) else ("partial" if found else "failed")
    job.finished_at = datetime.utcnow()
    db.commit()
    return job


def detect_duplicates(db: Session, threshold: float = 0.9) -> list[mx.MergeCandidate]:
    """ENR-004: merge candidates via hard keys (linkedin_url / confirmed email)
    or name similarity >= threshold within the same org."""
    persons = db.query(models.Person).filter(models.Person.is_active == True).all()  # noqa: E712
    out: list[mx.MergeCandidate] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(persons):
        for b in persons[i + 1:]:
            key = tuple(sorted([a.id, b.id]))
            if key in seen:
                continue
            sigs = {}
            if a.linkedin_url and a.linkedin_url == b.linkedin_url:
                sigs["linkedin_url"] = a.linkedin_url
            if a.primary_email and a.primary_email == b.primary_email:
                sigs["email"] = a.primary_email
            sim = SequenceMatcher(None, (a.full_name or "").lower(), (b.full_name or "").lower()).ratio()
            same_org = a.current_org_id and a.current_org_id == b.current_org_id
            if sigs or (sim >= threshold and same_org):
                mc = mx.MergeCandidate(entity_type="person", a_id=a.id, b_id=b.id,
                                       similarity=round(max(sim, 1.0 if sigs else sim), 3),
                                       signals=sigs or {"name_similarity": round(sim, 3)})
                db.add(mc); out.append(mc); seen.add(key)
    db.commit()
    return out
