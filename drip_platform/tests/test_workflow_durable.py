"""
Sprint 6 test — durable workflow execution: idempotent success replay, bounded
retry with backoff, dead-letter after max attempts, and retry_due re-drive.
SQLite + PostgreSQL.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_s6  # noqa: E402,F401
from abm_platform.services import workflow_durable as wd  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── idempotency: side effect runs once even if called twice ──
    calls = {"n": 0}

    def ok_action(ctx):
        calls["n"] += 1
        return {"did": "work", "n": calls["n"]}

    r1 = wd.execute_step(db, "run-1", "send", ok_action, idempotency_key="k1")
    r2 = wd.execute_step(db, "run-1", "send", ok_action, idempotency_key="k1")
    check("first execute succeeds", r1["status"] == "succeeded")
    check("second execute is idempotent replay", r2.get("idempotent_replay") is True)
    check("side effect ran exactly once", calls["n"] == 1)
    check("cached result returned", r2["result"]["did"] == "work")

    # ── bounded retry + dead-letter ──
    def flaky(ctx):
        raise RuntimeError("downstream 503")

    t0 = datetime.utcnow()
    a1 = wd.execute_step(db, "run-2", "call", flaky, idempotency_key="k2",
                         max_attempts=3, now=t0)
    check("attempt1 -> failed + scheduled", a1["status"] == "failed" and a1["attempts"] == 1)

    a2 = wd.execute_step(db, "run-2", "call", flaky, idempotency_key="k2",
                         max_attempts=3, now=t0)
    check("attempt2 -> failed", a2["status"] == "failed" and a2["attempts"] == 2)

    a3 = wd.execute_step(db, "run-2", "call", flaky, idempotency_key="k2",
                         max_attempts=3, now=t0)
    check("attempt3 -> dead_letter", a3["status"] == "dead_letter" and a3["attempts"] == 3)

    dl = wd.dead_letters(db)
    check("dead-letter queue has the step", len(dl) == 1 and dl[0]["node_id"] == "call")

    a4 = wd.execute_step(db, "run-2", "call", flaky, idempotency_key="k2", now=t0)
    check("dead-lettered step won't re-run", a4["status"] == "dead_letter")

    # ── retry_due re-drives a failed (not yet dead) step that now succeeds ──
    state = {"fail": True}

    def heals(ctx):
        if state["fail"]:
            raise RuntimeError("temporary")
        return {"ok": True}

    b1 = wd.execute_step(db, "run-3", "sync", heals, idempotency_key="k3",
                         max_attempts=5, now=t0)
    check("run-3 attempt1 failed", b1["status"] == "failed")

    state["fail"] = False  # downstream recovers

    def resolver(row):
        return heals, {}

    later = t0 + timedelta(hours=1)  # past the backoff window
    res = wd.retry_due(db, resolver, now=later)
    check("retry_due retried 1", res["retried"] == 1)
    check("retry_due succeeded 1", res["succeeded"] == 1)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_workflow_durable():
    assert run()
