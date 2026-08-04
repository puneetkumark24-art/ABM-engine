"""
Concurrency test for orchestrator._dispatch_human_approved — Postgres only.

A cron double-fire, or a human clicking "Run engine now" twice while the
first click is still in flight, means two ticks can genuinely run at the
same moment. Before this test existed, nothing proved that two concurrent
ticks can't both select and dispatch the SAME approved draft, which would
send a real duplicate email to a real prospect. orchestrator.py now locks
the draft rows it claims with `FOR UPDATE SKIP LOCKED` (Postgres only) so a
second concurrent tick silently skips whatever the first tick already has
locked instead of racing it.

This spins up two real threads, each with its OWN SQLAlchemy Session (own
DBAPI connection), synchronized with a Barrier so they call
_dispatch_human_approved at essentially the same instant against a shared
set of pre-seeded approved drafts -- the only way to actually exercise
FOR UPDATE SKIP LOCKED's row-level contention rather than just asserting
the code looks right.

Run: DATABASE_URL=postgresql+psycopg2://... python tests/test_concurrent_dispatch.py
"""
import os
import sys
import threading
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ext as mx  # noqa: E402
from sequences import engine as seq_engine  # noqa: E402
from abm_platform.services import orchestrator  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    is_pg = SessionLocal().bind.dialect.name == "postgresql"
    if not is_pg:
        print("… skipped (FOR UPDATE SKIP LOCKED needs real Postgres session concurrency; N/A on SQLite)")
        return True

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    org = models.Organization(canonical_name="Concurrency Test Bank")
    db.add(org); db.commit()

    N = 8
    people, drafts = [], []
    for i in range(N):
        p = models.Person(full_name=f"Concurrent Contact {i}", current_org_id=org.id,
                          primary_email=f"c{i}@example.invalid", consent_status="opted_in")
        db.add(p); db.commit()
        enr, _ = seq_engine.enroll_person(db, p.id)
        d = models.Draft(org_id=org.id, person_id=p.id, channel="email",
                         subject=f"step {i}", body=f"Hello contact {i}",
                         status="approved", source="ai", sequence_step=1,
                         reviewed_at=datetime.utcnow())
        db.add(d); db.commit()
        people.append(p); drafts.append(d)
    draft_ids = {d.id for d in drafts}

    barrier = threading.Barrier(2)
    thread_results = {}

    def worker(name):
        tdb = SessionLocal()
        try:
            barrier.wait(timeout=10)  # line both threads up to hit the DB together
            res = orchestrator._dispatch_human_approved(tdb, datetime.utcnow(), limit=N)
            thread_results[name] = res
        finally:
            tdb.close()

    t1 = threading.Thread(target=worker, args=("t1",))
    t2 = threading.Thread(target=worker, args=("t2",))
    t1.start(); t2.start()
    t1.join(timeout=20); t2.join(timeout=20)

    check("both threads completed", "t1" in thread_results and "t2" in thread_results)
    total_dispatched = thread_results.get("t1", {}).get("dispatched", 0) + \
                       thread_results.get("t2", {}).get("dispatched", 0)
    check("every draft dispatched exactly once across both threads (no double-send, none dropped)",
          total_dispatched == N)

    db.expire_all()
    sent = db.query(models.Draft).filter(models.Draft.id.in_(draft_ids), models.Draft.status == "sent").count()
    check("every draft ended up status=sent exactly once", sent == N)

    # the real proof against duplicate sends: exactly one SendRequest per
    # enrollment+step, never two, even though both threads raced for it.
    dupe_free = True
    for enr in db.query(models.SequenceEnrollment).filter(models.SequenceEnrollment.person_id.in_(
            [p.id for p in people])).all():
        n = db.query(mx.SendRequest).filter(
            mx.SendRequest.message_id == f"seq-{enr.id}-1").count()
        if n != 1:
            dupe_free = False
    check("exactly one SendRequest per enrollment (no duplicate dispatch)", dupe_free)

    db.close()
    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_concurrent_dispatch():
    assert run()
