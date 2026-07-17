"""
P0-D test — UUIDv7 ordering, set-based analytics, and Postgres range
partitioning (routing + pruning). Analytics + uuid7 run on both DBs; the
partitioning checks are Postgres-only.
"""
import os
import sys
import time
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
from abm_platform.services import uuid7, analytics, analytics_fast  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    is_pg = db.bind.dialect.name == "postgresql"

    # ── UUIDv7: time-ordered ──
    ids = []
    for _ in range(50):
        ids.append(uuid7.uuid7()); time.sleep(0.001)
    check("UUID7 are unique", len(set(ids)) == 50)
    check("UUID7 sort in creation order (index-friendly)", ids == sorted(ids))
    check("UUID7 embeds recent timestamp", abs(uuid7.uuid7_time(ids[-1]) - time.time()) < 5)

    # ── set-based analytics == naive ──
    for i in range(200):
        db.add(models_ext.MetricEvent(event_type=("open" if i % 2 else "click"),
                                      subject_id=f"s{i % 20}"))
    db.commit()
    naive = analytics.query(db, group_by="event_type")
    fast = analytics_fast.query_fast(db, group_by="event_type")
    check("ANALYTICS fast == naive (counts)", naive["groups"] == fast["groups"])
    check("ANALYTICS fast total correct", fast["total"] == 200 and fast["groups"]["open"] == 100)
    nf = analytics.funnel(db, ["open", "click"])
    ff = analytics_fast.funnel_fast(db, ["open", "click"])
    check("ANALYTICS funnel fast == naive",
          [(x["step"], x["count"]) for x in nf] == [(x["step"], x["count"]) for x in ff])

    # ── Postgres partitioning: routing + pruning ──
    if is_pg:
        from sqlalchemy import text
        # ensure the partition function + partitions for 3 months exist
        db.execute(text("SELECT create_month_partition(now()::date)"))
        db.execute(text("SELECT create_month_partition((now() - interval '2 month')::date)"))
        db.commit()
        db.execute(text("DELETE FROM metric_events_part"))
        db.commit()
        # insert into this month and two months ago
        db.execute(text("INSERT INTO metric_events_part (event_type, occurred_at) "
                        "VALUES ('e', now())"))
        db.execute(text("INSERT INTO metric_events_part (event_type, occurred_at) "
                        "VALUES ('e', now() - interval '2 month')"))
        db.commit()
        # rows land in DIFFERENT physical partitions (tableoid differs)
        parts = db.execute(text(
            "SELECT tableoid::regclass::text, count(*) FROM metric_events_part "
            "GROUP BY 1 ORDER BY 1")).fetchall()
        distinct_parts = {p[0] for p in parts}
        check("PARTITION rows routed to separate monthly partitions", len(distinct_parts) == 2)
        check("PARTITION each partition holds one row", all(p[1] == 1 for p in parts))
        # partition PRUNING: a this-month query plan scans only the current partition
        plan = "\n".join(r[0] for r in db.execute(text(
            "EXPLAIN SELECT * FROM metric_events_part "
            "WHERE occurred_at >= date_trunc('month', now())")).fetchall())
        this_month = "metric_events_part_" + datetime.utcnow().strftime("%Y_%m")
        old_month = "metric_events_part_" + (datetime.utcnow().replace(day=1) -
                                             timedelta(days=40)).strftime("%Y_%m")
        check("PARTITION pruning: plan hits current-month partition", this_month in plan)
        check("PARTITION pruning: plan excludes old partition", old_month not in plan)
    else:
        for nm in ["PARTITION rows routed to separate monthly partitions",
                   "PARTITION each partition holds one row",
                   "PARTITION pruning: plan hits current-month partition",
                   "PARTITION pruning: plan excludes old partition"]:
            check(nm + " (PG-only, skipped)", True)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_scale_db():
    assert run()
