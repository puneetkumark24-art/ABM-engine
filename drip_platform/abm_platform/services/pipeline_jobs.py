"""
pipeline_jobs.py — the rest of the autonomous loop as worker jobs.

The async orchestrator (P0-B) only wired `sequence_step`. This registers the
remaining autonomous operations as durable, retryable, concurrency-safe jobs so
the WHOLE zero-human loop runs on the worker fleet, not inline:

  decision          AI Decision Engine chooses the next touch for a person and
                    applies it (reschedule / handoff / hold) — replaces static
                    cadence with dynamic, explainable decisions.
  engagement_rollup recomputes a person/org's engagement -> account score ->
                    re-tier -> emits events. THIS closes the feedback loop that
                    the sync orchestrator did inline and the async one dropped.
  enrichment        waterfall-enriches a contact (providers registered at boot).
  campaign_send     sends a marketing campaign (dry_run) off the request path.

Plus schedulers that enqueue these on a beat, all idempotent.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
import models
import models_ext as mx
import models_jobs as mj
from . import decision, engagement, enrichment, marketing, jobs

# ── handlers ─────────────────────────────────────────────────
def handle_decision(db: Session, payload: dict) -> dict:
    person_id = payload["person_id"]
    dec = decision.decide(db, person_id)
    res = decision.apply_decision(db, dec.id)
    return {"action": dec.action, "confidence": dec.confidence, "applied": res}


def handle_engagement_rollup(db: Session, payload: dict) -> dict:
    return engagement.rollup_org(db, payload["org_id"])


def handle_enrichment(db: Session, payload: dict) -> dict:
    job = enrichment.run_waterfall(db, payload["person_id"], payload.get("required"))
    return {"status": job.status, "providers_tried": job.providers_tried}


def handle_campaign_send(db: Session, payload: dict) -> dict:
    return marketing.send_campaign(db, payload["campaign_id"], transport="dry_run")


def register_pipeline_handlers() -> None:
    jobs.register("decision", handle_decision)
    jobs.register("engagement_rollup", handle_engagement_rollup)
    jobs.register("enrichment", handle_enrichment)
    jobs.register("campaign_send", handle_campaign_send)


# ── schedulers (enqueue on a beat, idempotent) ───────────────
def schedule_engagement_rollups(db: Session, since_minutes: int = 60,
                                now: datetime | None = None) -> dict:
    """Enqueue a rollup per org that had a touch recently. Idempotency key =
    org:date-hour so we rescore each active org at most once per hour."""
    now = now or datetime.utcnow()
    org_ids = [r[0] for r in db.query(mx.Touch.org_id)
               .filter(mx.Touch.org_id.isnot(None))
               .group_by(mx.Touch.org_id).all()]
    stamp = now.strftime("%Y%m%d%H")
    enq = 0
    for org_id in org_ids:
        key = f"{org_id}:{stamp}"
        already = db.query(mj.Job).filter(mj.Job.kind == "engagement_rollup",
                                          mj.Job.idempotency_key == key).first()
        jobs.enqueue(db, "engagement_rollup", {"org_id": org_id},
                     idempotency_key=key, priority=200)
        if already is None:
            enq += 1
    return {"orgs": len(org_ids), "enqueued": enq}


def schedule_decisions(db: Session, limit: int = 500, now: datetime | None = None) -> dict:
    """Enqueue an AI decision for each person with an ACTIVE enrollment whose
    next step is due — the decision engine chooses/adjusts the next touch.
    Idempotency key = person:date-hour."""
    now = now or datetime.utcnow()
    stamp = now.strftime("%Y%m%d%H")
    active = (db.query(models.SequenceEnrollment.person_id)
              .filter(models.SequenceEnrollment.status == "ACTIVE",
                      models.SequenceEnrollment.next_run_at.isnot(None),
                      models.SequenceEnrollment.next_run_at <= now)
              .distinct().limit(limit).all())
    enq = 0
    for (pid,) in active:
        key = f"{pid}:{stamp}"
        already = db.query(mj.Job).filter(mj.Job.kind == "decision",
                                          mj.Job.idempotency_key == key).first()
        jobs.enqueue(db, "decision", {"person_id": pid}, idempotency_key=key, priority=150)
        if already is None:
            enq += 1
    return {"active_due": len(active), "enqueued": enq}
