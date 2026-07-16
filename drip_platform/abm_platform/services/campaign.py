"""Module 09 — Campaign Builder: the ABM wrapper grouping sequences, email
campaigns, landing pages and assets under one named play with unified rollup."""
from __future__ import annotations
from sqlalchemy.orm import Session
import models
import models_ext as mx


def create(db: Session, name: str, objective: str = "pipeline", budget: float = 0.0) -> mx.AbmCampaign:
    c = mx.AbmCampaign(name=name, objective=objective, budget=budget)
    db.add(c); db.commit()
    return c


def attach(db: Session, campaign_id: str, member_type: str, member_id: str) -> mx.AbmCampaignMember:
    existing = db.query(mx.AbmCampaignMember).filter_by(
        campaign_id=campaign_id, member_type=member_type, member_id=member_id).first()
    if existing:
        return existing
    m = mx.AbmCampaignMember(campaign_id=campaign_id, member_type=member_type, member_id=member_id)
    db.add(m); db.commit()
    return m


def activate(db: Session, campaign_id: str) -> mx.AbmCampaign:
    c = db.get(mx.AbmCampaign, campaign_id)
    c.status = "active"; db.commit()
    return c


def rollup(db: Session, campaign_id: str) -> dict:
    """Unified metrics across the campaign's members (CMP-001: only linked
    members contribute)."""
    members = db.query(mx.AbmCampaignMember).filter_by(campaign_id=campaign_id).all()
    out = {"members": len(members), "email": {"sent": 0, "opened": 0},
           "sequences": {"enrollments": 0, "completed": 0},
           "landing": {"submissions": 0}, "touches": 0}
    for m in members:
        if m.member_type == "email_campaign":
            msgs = db.query(mx.EmailMessage).filter_by(campaign_id=m.member_id).all()
            out["email"]["sent"] += len(msgs)
            ids = [x.id for x in msgs]
            if ids:
                out["email"]["opened"] += (db.query(mx.DeliveryEvent)
                    .filter(mx.DeliveryEvent.message_id.in_(ids),
                            mx.DeliveryEvent.event_type == "open").count())
        elif m.member_type == "sequence":
            q = db.query(models.SequenceEnrollment).filter_by(sequence_id=m.member_id)
            out["sequences"]["enrollments"] += q.count()
            out["sequences"]["completed"] += q.filter_by(status="COMPLETED").count()
        elif m.member_type == "landing_page":
            page = db.get(mx.LandingPage, m.member_id)
            if page and page.form_id:
                out["landing"]["submissions"] += db.query(mx.FormSubmission).filter_by(form_id=page.form_id).count()
        out["touches"] += db.query(mx.Touch).filter_by(campaign_id=campaign_id).count() if m.member_type == "org" else 0
    return out
