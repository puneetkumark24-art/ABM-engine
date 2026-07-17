"""
Gap-1 test — the FULL autonomous loop runs on the worker fleet and closes the
feedback loop: enroll -> scheduler enqueues step + decision + rollup jobs ->
workers process them -> drafts sent, decisions applied, account rescored/
re-tiered. Nothing runs inline in a request; every stage is a durable job.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_jobs as mj  # noqa: E402,F401
from sequences import engine as se  # noqa: E402
from abm_platform.services import (jobs, orchestrator_async, pipeline_jobs,  # noqa: E402
                                   enrichment, marketing, delivery)

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    jobs._HANDLERS.clear()
    orchestrator_async.register_handlers()
    pipeline_jobs.register_pipeline_handlers()
    enrichment.clear_providers()
    enrichment.register_provider("t", lambda p: {"current_title": p.current_title or "VP"})
    db = SessionLocal()

    check("LOOP all pipeline handlers registered",
          {"sequence_step", "decision", "engagement_rollup", "enrichment", "campaign_send"}
          <= set(jobs._HANDLERS.keys()))

    org = models.Organization(canonical_name="Auto Bank"); db.add(org); db.commit()
    people = []
    for i in range(4):
        p = models.Person(full_name=f"Auto {i}", current_org_id=org.id, tier="HOT",
                          primary_email=f"a{i}@ex.invalid", consent_status="opted_in",
                          seniority_level=("c_suite" if i == 0 else "vp"))
        people.append(p); db.add(p)
    db.commit()
    for p in people:
        se.enroll_person(db, p.id)
    for e in db.query(models.SequenceEnrollment).all():
        e.next_run_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    # ── scheduler enqueues step + decision jobs (no inline work) ──
    s = orchestrator_async.schedule_due_steps(db, respect_send_window=False)
    d = pipeline_jobs.schedule_decisions(db)
    check("LOOP scheduler enqueued step jobs", s["enqueued"] == 4)
    check("LOOP scheduler enqueued decision jobs", d["enqueued"] == 4)
    check("LOOP nothing sent yet (all queued)", db.query(models.Draft).count() == 0)

    # ── worker fleet processes everything ──
    jobs.run_worker(poll_seconds=0, batch=50, max_iterations=3)
    steps_done = db.query(mj.Job).filter_by(kind="sequence_step", status="done").count()
    dec_done = db.query(mj.Job).filter_by(kind="decision", status="done").count()
    check("LOOP worker processed all step jobs", steps_done == 4)
    check("LOOP worker processed all decision jobs", dec_done == 4)
    check("LOOP drafts produced by workers", db.query(models.Draft).count() >= 3)
    # c-suite held (person 0), others sent
    held = db.query(models.Draft).filter_by(status="pending").count()
    sent = db.query(models.Draft).filter_by(status="sent").count()
    check("LOOP c-suite draft held for human by worker", held >= 1)
    check("LOOP non-c-suite drafts sent (dry-run) by worker", sent >= 3)
    check("LOOP decisions logged with reasoning", db.query(models_p11.DecisionLog).count() == 4)

    # ── feedback loop closes async: rollup job rescoring ──
    # simulate engagement events, then schedule + run rollup jobs
    msg = db.query(models_ext.EmailMessage).first()
    if msg:
        delivery.ingest_webhook(db, [{"id": "x1", "message_id": msg.id, "type": "open", "ts": 1},
                                     {"id": "x2", "message_id": msg.id, "type": "click", "ts": 2}])
    rl = pipeline_jobs.schedule_engagement_rollups(db)
    check("LOOP scheduler enqueued engagement rollups", rl["enqueued"] >= 1)
    jobs.run_worker(poll_seconds=0, batch=50, max_iterations=2)
    check("LOOP rollup jobs completed",
          db.query(mj.Job).filter_by(kind="engagement_rollup", status="done").count() >= 1)
    check("LOOP account rescored by worker (feedback loop closed async)",
          db.query(models.AccountScore).filter(
              models.AccountScore.notes.like("%Phase 10%")).count() >= 1)
    acct = db.get(models.AccountIntelligence, org.id)
    check("LOOP account tier persisted", acct is not None and acct.priority in ("HOT", "WARM", "COLD"))

    # ── enrichment + campaign_send jobs also run on the fleet ──
    jobs.enqueue(db, "enrichment", {"person_id": people[1].id}, idempotency_key="e1")
    aud = marketing.create_audience(db, "auto list"); marketing.add_members(db, aud.id, [people[1].id])
    camp = marketing.create_campaign(db, "auto camp", aud.id, "s", "b")
    jobs.enqueue(db, "campaign_send", {"campaign_id": camp.id}, idempotency_key="cs1")
    jobs.run_worker(poll_seconds=0, batch=50, max_iterations=2)
    check("LOOP enrichment job ran on worker",
          db.query(mj.Job).filter_by(kind="enrichment", status="done").count() == 1)
    check("LOOP campaign_send job ran on worker",
          db.query(mj.Job).filter_by(kind="campaign_send", status="done").count() == 1)

    # ── everything durable: no dead jobs, all terminal ──
    dead = db.query(mj.Job).filter_by(status="dead").count()
    queued = db.query(mj.Job).filter_by(status="queued").count()
    check("LOOP no dead jobs", dead == 0)
    check("LOOP no stuck queued jobs", queued == 0)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


import models_p11  # noqa: E402  (used above)

if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_autonomous_loop():
    assert run()
