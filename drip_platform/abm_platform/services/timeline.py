"""AI Timeline assembler — the unified, chronologically-merged history of a
person (or organization) across every store: activities, sequence events,
delivery events, LinkedIn actions, form submissions, AI generations, touches.
The CRM 'AI timeline' the match report flagged as missing — the data always
existed; this merges it."""
from __future__ import annotations
from sqlalchemy.orm import Session
import models
import models_ext as mx


def person_timeline(db: Session, person_id: str, limit: int = 100) -> list[dict]:
    entries: list[dict] = []

    for a in db.query(models.ActivityLog).filter_by(person_id=person_id).all():
        entries.append({"at": a.timestamp, "kind": f"activity:{a.activity_type}",
                        "detail": a.notes or a.outcome or "", "source": "activity_log"})

    enr_ids = [e.id for e in db.query(models.SequenceEnrollment)
               .filter_by(person_id=person_id).all()]
    if enr_ids:
        for ev in (db.query(models.SequenceEnrollmentEvent)
                   .filter(models.SequenceEnrollmentEvent.enrollment_id.in_(enr_ids)).all()):
            entries.append({"at": ev.created_at, "kind": f"sequence:{ev.event_type}",
                            "detail": ev.detail or f"step {ev.step_number}",
                            "source": "sequence_engine"})

    msg_ids = [m.id for m in db.query(mx.EmailMessage).filter_by(person_id=person_id).all()]
    if msg_ids:
        for de in (db.query(mx.DeliveryEvent)
                   .filter(mx.DeliveryEvent.message_id.in_(msg_ids)).all()):
            entries.append({"at": de.occurred_at, "kind": f"email:{de.event_type}",
                            "detail": de.provider, "source": "delivery"})

    for la in db.query(mx.LiAction).filter_by(person_id=person_id).all():
        entries.append({"at": la.executed_at or la.scheduled_at,
                        "kind": f"linkedin:{la.action_type}:{la.status}",
                        "detail": la.detail or "", "source": "linkedin"})

    for fs in db.query(mx.FormSubmission).filter_by(person_id=person_id).all():
        entries.append({"at": fs.created_at, "kind": "form:submitted",
                        "detail": f"consent={fs.consent_given}", "source": "landing"})

    for g in db.query(mx.AiGeneration).filter_by(person_id=person_id).all():
        entries.append({"at": g.created_at, "kind": f"ai:{g.kind}:{g.status}",
                        "detail": (g.output or "")[:80], "source": "ai_gen"})

    for t in db.query(mx.Touch).filter_by(person_id=person_id).all():
        entries.append({"at": t.occurred_at, "kind": f"touch:{t.channel}",
                        "detail": t.campaign_id or "", "source": "attribution"})

    entries = [e for e in entries if e["at"] is not None]
    entries.sort(key=lambda e: e["at"], reverse=True)
    return entries[:limit]


def org_timeline(db: Session, org_id: str, limit: int = 100) -> list[dict]:
    """Org view: all persons' timelines + org-level activities & signals."""
    entries: list[dict] = []
    persons = db.query(models.Person).filter_by(current_org_id=org_id).all()
    for p in persons:
        for e in person_timeline(db, p.id, limit=30):
            e["person"] = p.full_name
            entries.append(e)
    for a in db.query(models.ActivityLog).filter_by(org_id=org_id, person_id=None).all():
        entries.append({"at": a.timestamp, "kind": f"activity:{a.activity_type}",
                        "detail": a.notes or "", "source": "activity_log"})
    for s in (db.query(models.Signal).filter_by(org_id=org_id)
              .order_by(models.Signal.created_at.desc()).limit(20).all()):
        entries.append({"at": s.created_at, "kind": f"signal:{s.signal_type}",
                        "detail": (s.title or "")[:80], "source": "signals"})
    entries = [e for e in entries if e["at"] is not None]
    entries.sort(key=lambda e: e["at"], reverse=True)
    return entries[:limit]
