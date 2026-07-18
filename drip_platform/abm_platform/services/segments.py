"""
segments.py — Parity Mission: segmentation engine.

Dynamic segments: AND-combined condition rules over Person fields plus the
engagement dimension (engagement_score via PersonEngagement) — evaluated live
at read time, Mailchimp-style. Static lists: explicit membership add/remove,
HubSpot-style. Both share SegmentDef; audiences/campaigns can resolve members
through one call.

Supported ops: eq, neq, contains (icase), gt, lt, in, exists.
Special fields: engagement_score (joined), has_replied (Person.replied).
"""
from __future__ import annotations
from sqlalchemy.orm import Session
import models
import models_p10 as p10
import models_segments as ms

_OPS = {"eq", "neq", "contains", "gt", "lt", "in", "exists"}


def create_segment(db: Session, name: str, conditions: list[dict],
                   is_dynamic: bool = True) -> ms.SegmentDef:
    for c in conditions:
        if "field" not in c or c.get("op", "eq") not in _OPS:
            raise ValueError(f"bad condition {c}; op must be one of {sorted(_OPS)}")
    seg = ms.SegmentDef(name=name, conditions=conditions, is_dynamic=is_dynamic)
    db.add(seg); db.commit()
    return seg


def add_to_list(db: Session, segment_id: str, person_id: str) -> bool:
    seg = db.get(ms.SegmentDef, segment_id)
    if seg is None:
        raise ValueError("segment not found")
    if seg.is_dynamic:
        raise ValueError("cannot add members to a dynamic segment")
    if db.query(ms.ListMembership).filter_by(segment_id=segment_id,
                                             person_id=person_id).first():
        return False
    db.add(ms.ListMembership(segment_id=segment_id, person_id=person_id))
    db.commit()
    return True


def remove_from_list(db: Session, segment_id: str, person_id: str) -> bool:
    row = (db.query(ms.ListMembership)
           .filter_by(segment_id=segment_id, person_id=person_id).first())
    if row is None:
        return False
    db.delete(row); db.commit()
    return True


def _person_value(db: Session, person: models.Person, field: str):
    if field == "engagement_score":
        e = db.query(p10.PersonEngagement).filter_by(person_id=person.id).first()
        return e.engagement_score if e else 0.0
    if field == "has_replied":
        return bool(person.replied)
    return getattr(person, field, None)


def _matches(db: Session, person: models.Person, conditions: list[dict]) -> bool:
    for c in conditions:
        v = _person_value(db, person, c["field"])
        op, target = c.get("op", "eq"), c.get("value")
        ok = (
            (op == "eq" and v == target) or
            (op == "neq" and v != target) or
            (op == "contains" and target is not None and
             str(target).lower() in str(v or "").lower()) or
            (op == "gt" and v is not None and target is not None and v > target) or
            (op == "lt" and v is not None and target is not None and v < target) or
            (op == "in" and v in (target or [])) or
            (op == "exists" and v not in (None, ""))
        )
        if not ok:
            return False
    return True


def evaluate(db: Session, segment_id: str, limit: int = 1000) -> list[models.Person]:
    seg = db.get(ms.SegmentDef, segment_id)
    if seg is None:
        raise ValueError("segment not found")
    if not seg.is_dynamic:
        rows = (db.query(ms.ListMembership)
                .filter_by(segment_id=segment_id).limit(limit).all())
        people = [db.get(models.Person, r.person_id) for r in rows]
        return [p for p in people if p is not None]
    out = []
    for p in db.query(models.Person).filter(models.Person.is_active == True).all():  # noqa: E712
        if _matches(db, p, seg.conditions or []):
            out.append(p)
            if len(out) >= limit:
                break
    return out


def segment_summary(db: Session, segment_id: str) -> dict:
    seg = db.get(ms.SegmentDef, segment_id)
    members = evaluate(db, segment_id)
    return {"id": seg.id, "name": seg.name,
            "type": "dynamic" if seg.is_dynamic else "static",
            "conditions": seg.conditions, "size": len(members),
            "sample": [{"id": p.id, "name": p.full_name} for p in members[:10]]}
