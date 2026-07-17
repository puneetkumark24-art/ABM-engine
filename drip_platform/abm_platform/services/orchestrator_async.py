"""
orchestrator_async.py — the scale version of the zero-human loop (P0-B).

The old orchestrator.run_tick ran everything inline in one blocking loop (BOMB
5). This splits it:

  schedule_due_steps(db)   the SCHEDULER: finds due sequence steps and ENQUEUES
                           one job each (idempotent by enrollment+step). Fast,
                           does no AI/sending. Runs on a beat.
  handle_sequence_step()   the HANDLER (registered as job kind 'sequence_step'):
                           one enrollment's next step — gate → AI draft →
                           dry-run send → advance → touch → emit outbox event.
                           Runs on a WORKER, in its own session, retryable.

Result: thousands of due steps become thousands of independent, retryable,
concurrency-safe jobs processed by a horizontally-scalable worker pool instead
of one blocking tick. c-suite hold + dry-run-only remain enforced in the handler.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_jobs as mj
from sequences import engine as seq_engine
from . import ai_gen, delivery, attribution, jobs

JOB_KIND = "sequence_step"


def schedule_due_steps(db: Session, limit: int = 500, respect_send_window: bool = True,
                       now: datetime | None = None) -> dict:
    """Enqueue a job per due enrollment step. Idempotency key = enrollment:step
    so re-running the scheduler never double-enqueues the same step."""
    now = now or datetime.utcnow()
    due = seq_engine.get_due(db, limit=limit, respect_send_window=respect_send_window, now=now)
    enqueued = 0
    for row in due:
        enr, step = row["enrollment"], row["next_step"]
        key = f"{enr.id}:{step.step_number}"
        already = (db.query(mj.Job)
                   .filter(mj.Job.kind == JOB_KIND, mj.Job.idempotency_key == key).first())
        jobs.enqueue(db, JOB_KIND,
                     payload={"enrollment_id": enr.id, "step_number": step.step_number},
                     tenant_id=getattr(enr, "tenant_id", None), idempotency_key=key)
        if already is None:
            enqueued += 1
    return {"due": len(due), "enqueued": enqueued}


def handle_sequence_step(db: Session, payload: dict) -> dict:
    """Worker handler for one sequence step. Its own transaction; raising here
    triggers the job runtime's retry/backoff — no batch is aborted."""
    enr = db.get(models.SequenceEnrollment, payload["enrollment_id"])
    if enr is None or enr.status != "ACTIVE":
        return {"skipped": "enrollment not active"}
    step = seq_engine._next_step(db, enr.sequence_id, enr.current_step)
    if step is None or step.step_number != payload["step_number"]:
        return {"skipped": "step no longer current"}
    person = db.get(models.Person, enr.person_id)
    ok, reason = seq_engine.is_contactable(person)
    if not ok:
        return {"skipped": f"not contactable: {reason}"}

    gen = ai_gen.generate(db, "email", person_id=person.id, org_id=enr.org_id,
                          context={"sequence_step": step.step_number, "channel": step.channel})
    if gen.status != "qc_passed":
        return {"qc_failed": (gen.qc or {}).get("issues")}
    held = any("human approval" in i for i in (gen.qc or {}).get("issues", []))
    draft = models.Draft(org_id=enr.org_id, person_id=person.id, channel="email",
                         subject=f"Step {step.step_number}", body=gen.output,
                         status="pending" if held else "approved", source="ai",
                         sequence_step=step.step_number)
    db.add(draft); db.flush()
    if held:
        db.commit()
        return {"held_for_human": True, "draft_id": draft.id}

    req = delivery.enqueue(db, message_id=f"seq-{enr.id}-{step.step_number}",
                           to_email=person.primary_email or "missing@example.invalid",
                           subject=draft.subject, body=draft.body, transport="dry_run")
    draft.status = "sent"; draft.sent_at = datetime.utcnow()
    seq_engine.advance(db, enr.id)
    attribution.record_touch(db, org_id=enr.org_id, person_id=person.id, channel="email")
    jobs.outbox_emit(db, "sequence.step.sent", event_key=enr.org_id,
                     payload={"person_id": person.id, "step": step.step_number},
                     tenant_id=getattr(enr, "tenant_id", None))
    db.commit()
    return {"sent_dry_run": True, "send_request": req.id, "draft_id": draft.id}


def register_handlers() -> None:
    jobs.register(JOB_KIND, handle_sequence_step)
