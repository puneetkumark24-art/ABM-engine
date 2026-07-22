"""
crm_sync.py — AI Intelligence Layer Sprint 6: wires an accepted
NbaRecommendation into Module 06's native CRM (Opportunity + ActivityLog),
per the 2026-07-21 decision that the native CRM/Marketing engines are the
system of record and HubSpot stays out of the primary path entirely (no
sync code written against it — see
transformation/AI_Intelligence_Layer_Production_Architecture.md section 9,
resolved open question).

Design: accepting an NBA recommendation is a HUMAN action — mirrors
bank_intelligence_agent.py's own discipline that nba_recommendations are
"deliberately NOT auto-executed." This module's entry point,
accept_recommendation(), is what a human clicking "Accept" in the
dashboard calls; nothing here runs autonomously off an NBA's mere
existence. The AI layer proposes, a human (or, in the future, the
existing decision.py policy engine) accepts.

What "accept" writes:
  - an ActivityLog row (Universal Activity Engine, PRD §12) — the
    permanent record that this NBA was acted on, linked to the
    org/opportunity/person it concerns.
  - an Opportunity row IF one doesn't already exist in an open stage for
    this org (an NBA like 'escalate_rfp' implies active pursuit; it's
    wrong to silently create a second parallel Opportunity if one's
    already being worked).
  - a Notification to the owning rep via notification.py's existing
    send() surface (Sprint 6's other half: real Slack/email channels now
    exist behind that same seam).
  - the NbaRecommendation row itself flips to status='accepted'
    (idempotent — accepting twice is a no-op on the second call).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

import models
import models_intel as mi
from . import notification

# action_code -> (activity_type, default priority)
ACTION_TYPE_MAP = {
    "escalate_rfp": ("rfp", "high"),
    "schedule_briefing": ("meeting", "high"),
    "warm_intro": ("linkedin", "med"),
    "send_content": ("email", "med"),
}
DEFAULT_ACTIVITY_TYPE = "note"


def _find_or_create_opportunity(db: Session, org_id: str, product_id: str | None) -> models.Opportunity:
    open_stages = ["Identified", "Qualified", "Proposal", "Negotiation"]
    existing = (
        db.query(models.Opportunity)
        .filter(models.Opportunity.org_id == org_id, models.Opportunity.stage.in_(open_stages))
        .order_by(models.Opportunity.updated_at.desc())
        .first()
    )
    if existing:
        return existing
    opp = models.Opportunity(org_id=org_id, product_id=product_id, stage="Identified", probability=10)
    db.add(opp); db.flush()
    return opp


def accept_recommendation(db: Session, nba_id: str, owner: str = "Puneet",
                          create_opportunity: bool = True) -> dict:
    """The single entry point. Idempotent: accepting an already-accepted
    recommendation returns the prior result without writing duplicate
    ActivityLog/Notification rows."""
    nba = db.get(mi.NbaRecommendation, nba_id)
    if nba is None:
        return {"error": "nba_recommendation not found"}
    if nba.status == "accepted":
        return {"status": "already_accepted", "nba_id": nba_id}

    activity_type, default_priority = ACTION_TYPE_MAP.get(nba.action_code, (DEFAULT_ACTIVITY_TYPE, "med"))

    opportunity = None
    if create_opportunity:
        opportunity = _find_or_create_opportunity(db, nba.org_id, product_id=None)

    activity = models.ActivityLog(
        activity_type=activity_type, org_id=nba.org_id,
        opportunity_id=opportunity.id if opportunity else None,
        owner=owner, priority=default_priority,
        notes=nba.rationale, next_action=nba.action_code,
        timestamp=datetime.utcnow(),
    )
    db.add(activity); db.flush()

    org = db.get(models.Organization, nba.org_id)
    notif = notification.send(
        db, owner, kind="nba_accepted",
        payload={
            "org": org.canonical_name if org else nba.org_id,
            "action_code": nba.action_code,
            "rationale": nba.rationale,
            "opportunity_id": opportunity.id if opportunity else None,
            "activity_id": activity.id,
        },
        priority="high" if default_priority == "high" else "med",
    )

    nba.status = "accepted"
    db.add(nba)
    db.commit()

    return {
        "status": "accepted", "nba_id": nba.id,
        "activity_id": activity.id,
        "opportunity_id": opportunity.id if opportunity else None,
        "notification_id": notif.id,
    }


def dismiss_recommendation(db: Session, nba_id: str) -> dict:
    nba = db.get(mi.NbaRecommendation, nba_id)
    if nba is None:
        return {"error": "nba_recommendation not found"}
    nba.status = "dismissed"
    db.add(nba); db.commit()
    return {"status": "dismissed", "nba_id": nba_id}
