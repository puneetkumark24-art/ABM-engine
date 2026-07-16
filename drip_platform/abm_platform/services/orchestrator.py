"""The end-to-end orchestrator — one tick runs the whole engine:

  due sequence steps (compliance + KSA-window gated)
    -> AI draft (anonymized, QC'd; c-suite auto-held for human)
    -> Draft record (pending / auto-approvable per QC)
    -> dry-run delivery (idempotent, evented)
    -> sequence advance
    -> attribution touch + analytics event
  then for every touched org:
    -> engagement rollup -> account_scores -> re-tier -> events

This is the 'zero human intervention' loop in embryo, with the three hard
stops intact: c-suite drafts are never auto-approved, nothing sends for real
(dry_run transport only), and every gate lives in the called service, not here.
Run it from a scheduler (cron / engine_scheduler) or POST /engine/tick."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
from sequences import engine as seq_engine
from . import ai_gen, delivery, attribution, analytics, engagement

def run_tick(db: Session, limit: int = 10, respect_send_window: bool = True,
             now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    report = {"due": 0, "drafted": 0, "held_for_human": 0, "qc_failed": 0,
              "sent_dry_run": 0, "advanced": 0, "orgs_rescored": [], "skipped": None}

    due = seq_engine.get_due(db, limit=limit, respect_send_window=respect_send_window, now=now)
    if not due and respect_send_window:
        allowed, reason = __import__("sequences.send_window", fromlist=["is_within_send_window"]).is_within_send_window()
        if not allowed:
            report["skipped"] = f"send window closed: {reason}"
            return report
    report["due"] = len(due)

    touched_orgs: set[str] = set()
    for row in due:
        person, enr, step = row["person"], row["enrollment"], row["next_step"]

        # 1) AI draft (anonymized + QC). c-suite => held for human, not sent.
        gen = ai_gen.generate(db, "email", person_id=person.id, org_id=enr.org_id,
                              context={"sequence_step": step.step_number,
                                       "channel": step.channel})
        if gen.status != "qc_passed":
            report["qc_failed"] += 1
            continue
        held = any("human approval" in i for i in (gen.qc or {}).get("issues", []))
        draft = models.Draft(org_id=enr.org_id, person_id=person.id,
                             channel="email", subject=f"Step {step.step_number}",
                             body=gen.output,
                             status="pending" if held else "approved",
                             source="ai", sequence_step=step.step_number)
        db.add(draft); db.flush()
        report["drafted"] += 1
        if held:
            report["held_for_human"] += 1
            continue                       # c-suite: stops here until a human approves

        # 2) dry-run delivery (idempotent per enrollment+step)
        req = delivery.enqueue(db, message_id=f"seq-{enr.id}-{step.step_number}",
                               to_email=person.primary_email or "missing@example.invalid",
                               subject=draft.subject, body=draft.body,
                               transport="dry_run")
        if req.status == "sent":
            report["sent_dry_run"] += 1
            draft.status = "sent"; draft.sent_at = now

        # 3) advance the sequence + record the touch
        seq_engine.advance(db, enr.id, now=now)
        report["advanced"] += 1
        attribution.record_touch(db, org_id=enr.org_id, person_id=person.id,
                                 channel="email", occurred_at=now)
        analytics.ingest(db, "sequence.step.sent", subject_type="person",
                         subject_id=person.id, props={"step": step.step_number})
        if enr.org_id:
            touched_orgs.add(enr.org_id)

    # 4) close the loop: engagement rollup + rescore + re-tier per touched org
    for org_id in touched_orgs:
        result = engagement.rollup_org(db, org_id)
        report["orgs_rescored"].append({"org_id": org_id, **result})

    db.commit()
    return report
