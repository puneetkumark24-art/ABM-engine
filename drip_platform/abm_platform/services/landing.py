"""Module 13 — Landing Pages & Forms.
LP-001: forms capturing contactable data require explicit consent and store
proof. LP-002: submissions upsert the Person (no blind duplicates) via email
match. Unsub/preference writes go straight to suppression."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_ext as mx
from . import marketing
from abm_platform.events import Event, publish


def create_form(db: Session, name: str, fields: list[dict], consent_required: bool = True) -> mx.FormDef:
    f = mx.FormDef(name=name, fields=fields, consent_required=consent_required)
    db.add(f); db.commit()
    return f


def create_page(db: Session, slug: str, title: str, form_id: str | None = None,
                asset_id: str | None = None) -> mx.LandingPage:
    p = mx.LandingPage(slug=slug, title=title, form_id=form_id, asset_id=asset_id, status="published")
    db.add(p); db.commit()
    return p


def submit(db: Session, form_id: str, data: dict, utm: dict | None = None,
           consent_given: bool = False) -> tuple[mx.FormSubmission | None, str]:
    form = db.get(mx.FormDef, form_id)
    if form is None:
        return None, "form_not_found"
    # required-field validation
    for f in (form.fields or []):
        if f.get("required") and not data.get(f["key"]):
            return None, f"missing_required:{f['key']}"
    email = (data.get("email") or "").strip().lower()
    if form.consent_required and not consent_given:      # LP-001
        return None, "consent_required"

    # LP-002: upsert person by email
    person = None
    if email:
        person = db.query(models.Person).filter(models.Person.primary_email == email).first()
        if person is None:
            person = models.Person(
                full_name=data.get("name") or email.split("@")[0].title(),
                primary_email=email,
                data_source="landing_form",
                email_confidence="Self-reported",
            )
            db.add(person); db.flush()
        if consent_given:
            person.consent_status = "opted_in"
            person.consent_date = datetime.utcnow()
            person.consent_source = f"form:{form.name}"

    sub = mx.FormSubmission(form_id=form_id, person_id=person.id if person else None,
                            email=email, data=data, utm=utm or {}, consent_given=consent_given)
    db.add(sub); db.commit()
    publish(Event("form.submitted", key=form_id, payload={"email": email}))
    return sub, "ok"


def unsubscribe(db: Session, email: str) -> dict:
    """Preference/unsub center write: suppress globally + flip consent."""
    marketing.suppress(db, email, reason="unsub")
    person = db.query(models.Person).filter(models.Person.primary_email == email.lower()).first()
    if person:
        person.consent_status = "denied"
        person.do_not_contact = True
        db.commit()
    return {"unsubscribed": email}
