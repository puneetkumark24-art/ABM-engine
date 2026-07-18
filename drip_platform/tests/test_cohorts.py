"""
Sprint 7 test — cohort retention matrix + time-series trends over metric_events.
Deterministic synthetic events. SQLite + PostgreSQL.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
from abm_platform.services import cohorts  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def _ev(db, et, sid, occ):
    db.add(models_ext.MetricEvent(event_type=et, subject_type="person",
                                  subject_id=sid, props={}, occurred_at=occ))


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    now = datetime(2026, 7, 18, 12, 0, 0)
    start = now - timedelta(days=28)  # 4 weekly periods

    # Cohort A (week 0): 10 signups; 5 return in week1, 2 in week2
    for i in range(10):
        sid = f"A{i}"
        _ev(db, "signup", sid, start + timedelta(days=1))
        if i < 5:
            _ev(db, "active", sid, start + timedelta(days=8))   # week1
        if i < 2:
            _ev(db, "active", sid, start + timedelta(days=15))  # week2
    # Cohort B (week 1): 4 signups; 1 returns in its week1
    for i in range(4):
        sid = f"B{i}"
        _ev(db, "signup", sid, start + timedelta(days=8))
        if i < 1:
            _ev(db, "active", sid, start + timedelta(days=15))
    db.commit()

    # ── time series ──
    ts = cohorts.timeseries(db, "signup", since_days=28, bucket_days=7, now=now)
    check("timeseries has 4 weekly buckets", len(ts) == 4)
    check("week0 has 10 signups", ts[0]["count"] == 10)
    check("week1 has 4 signups", ts[1]["count"] == 4)

    # ── cohort retention ──
    ret = cohorts.cohort_retention(db, "signup", "active", period_days=7,
                                   periods=3, since_days=28, now=now)
    cohort_map = {c["cohort_start"]: c for c in ret["cohorts"]}
    a = ret["cohorts"][0]
    check("cohort A size 10", a["size"] == 10)
    check("cohort A period0 = 100%", a["retention_pct"][0] == 100.0)
    check("cohort A period1 = 50% (5/10)", a["retention_pct"][1] == 50.0)
    check("cohort A period2 = 20% (2/10)", a["retention_pct"][2] == 20.0)
    check("two cohorts detected (A + B)", len(ret["cohorts"]) == 2)
    b = ret["cohorts"][1]
    check("cohort B size 4", b["size"] == 4)
    check("cohort B period1 = 25% (1/4)", b["retention_pct"][1] == 25.0)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_cohorts():
    assert run()
