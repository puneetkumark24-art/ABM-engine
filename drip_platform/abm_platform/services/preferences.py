"""
preferences.py — Final wave: the public preference center (Mailchimp gap).

Each person gets a signed, unguessable link: /p/prefs/{person_id}/{token}
(token = HMAC of person_id with JWT_SECRET — no login needed, not forgeable).
They can toggle subscription categories or unsubscribe from everything, which
suppresses the address and sets do_not_contact (wired into the existing
send-safety machinery).
"""
from __future__ import annotations
import hashlib
import hmac
import os
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_final as mf

CATEGORIES = ["product_updates", "insights", "events", "partnership"]


def _secret() -> bytes:
    return os.environ.get("JWT_SECRET", "drip-dev-jwt-secret-change-me").encode()


def token_for(person_id: str) -> str:
    return hmac.new(_secret(), f"prefs:{person_id}".encode(), hashlib.sha256).hexdigest()[:24]


def verify_token(person_id: str, token: str) -> bool:
    return hmac.compare_digest(token_for(person_id), token or "")


def get_profile(db: Session, person_id: str) -> dict:
    p = db.get(models.Person, person_id)
    if p is None:
        raise ValueError("person not found")
    prof = db.query(mf.PreferenceProfile).filter_by(person_id=person_id).first()
    cats = (prof.categories if prof else None) or {c: True for c in CATEGORIES}
    return {"person_id": person_id, "name": p.full_name,
            "unsubscribed_all": bool(p.do_not_contact),
            "categories": {c: bool(cats.get(c, True)) for c in CATEGORIES}}


def update_profile(db: Session, person_id: str, categories: dict | None = None,
                   unsubscribe_all: bool = False) -> dict:
    p = db.get(models.Person, person_id)
    if p is None:
        raise ValueError("person not found")
    prof = db.query(mf.PreferenceProfile).filter_by(person_id=person_id).first()
    if prof is None:
        prof = mf.PreferenceProfile(person_id=person_id, categories={})
        db.add(prof)
    if categories is not None:
        prof.categories = {c: bool(categories.get(c, False)) for c in CATEGORIES}
    if unsubscribe_all:
        p.do_not_contact = True
        p.consent_status = "withdrawn"
        if p.primary_email and not db.query(mx.Suppression).filter_by(
                email=p.primary_email).first():
            db.add(mx.Suppression(email=p.primary_email, reason="preference-center"))
    else:
        # re-subscribing through the center restores contactability for chosen cats
        if categories is not None and any(categories.values()):
            p.do_not_contact = False
            if p.consent_status == "withdrawn":
                p.consent_status = "granted"
    db.commit()
    return get_profile(db, person_id)


def may_send(db: Session, person_id: str, category: str) -> bool:
    """Campaign-time check: is this person opted in for this category?"""
    prof = get_profile(db, person_id)
    if prof["unsubscribed_all"]:
        return False
    return bool(prof["categories"].get(category, True))
