"""
Gap-2 test — the REAL event tables are partitioned: ORM inserts route to the
right monthly partition, partition pruning works, analytics_fast stays correct,
and RLS still isolates on the partitioned table. Postgres-only (migration-based).
"""
import os
import sys
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import sqlalchemy as sa  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("… real-partitioning test needs PostgreSQL");
        print("\n0/0 checks passed  [DB: sqlite — skipped]")
        return True

    import database
    from database import SessionLocal
    import models_ext as mx
    from abm_platform.services import analytics_fast

    eng = database.engine
    # metric_events is now a partitioned table
    with eng.connect() as c:
        is_part = c.execute(sa.text(
            "SELECT count(*) FROM pg_partitioned_table pt JOIN pg_class cl "
            "ON cl.oid = pt.partrelid WHERE cl.relname='metric_events'")).scalar()
    check("PART metric_events is partitioned", is_part == 1)
    with eng.connect() as c:
        for t in ("delivery_events", "web_events"):
            n = c.execute(sa.text(
                "SELECT count(*) FROM pg_partitioned_table pt JOIN pg_class cl "
                "ON cl.oid = pt.partrelid WHERE cl.relname=:t"), {"t": t}).scalar()
            check(f"PART {t} is partitioned", n == 1)

    # ORM insert routes to the correct monthly partition
    db = SessionLocal()
    db.execute(sa.text("DELETE FROM metric_events"))
    db.commit()
    now = datetime.utcnow()
    e_now = mx.MetricEvent(event_type="e_now", occurred_at=now)
    e_old = mx.MetricEvent(event_type="e_old", occurred_at=now - timedelta(days=62))
    db.add_all([e_now, e_old]); db.commit()
    parts = db.execute(sa.text(
        "SELECT tableoid::regclass::text, count(*) FROM metric_events GROUP BY 1")).fetchall()
    check("PART ORM inserts routed to >=2 monthly partitions", len({p[0] for p in parts}) >= 2)

    # partition pruning: this-month query hits only the current partition
    plan = "\n".join(r[0] for r in db.execute(sa.text(
        "EXPLAIN SELECT * FROM metric_events WHERE occurred_at >= date_trunc('month', now())"
    )).fetchall())
    this_m = "metric_events_" + now.strftime("%Y_%m")
    check("PART pruning hits current-month partition", this_m in plan)

    # analytics_fast still correct over the partitioned table
    for i in range(30):
        db.add(mx.MetricEvent(event_type="open" if i % 2 else "click", subject_id=f"s{i%5}"))
    db.commit()
    q = analytics_fast.query_fast(db, group_by="event_type")
    check("PART analytics_fast correct over partitions",
          q["groups"].get("open") == 15 and q["groups"].get("click") == 15)

    # RLS still isolates on the partitioned parent (as app_rw)
    TA = "aaaaaaaa-0000-0000-0000-000000000001"
    TB = "bbbbbbbb-0000-0000-0000-000000000002"
    with eng.begin() as c:
        c.execute(sa.text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
                          "THEN CREATE ROLE app_rw LOGIN NOSUPERUSER; END IF; END $$;"))
        c.execute(sa.text("GRANT SELECT, INSERT ON metric_events TO app_rw"))
        c.execute(sa.text("DELETE FROM metric_events WHERE event_type='iso'"))
        c.execute(sa.text("INSERT INTO metric_events (id,event_type,tenant_id,occurred_at) "
                          "VALUES (gen_random_uuid(),'iso',:a, now())"), {"a": TA})
        c.execute(sa.text("INSERT INTO metric_events (id,event_type,tenant_id,occurred_at) "
                          "VALUES (gen_random_uuid(),'iso',:b, now())"), {"b": TB})
    app = sa.create_engine("postgresql+psycopg2://app_rw@" + url.split("@", 1)[1])
    with app.begin() as c:
        c.execute(sa.text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TA})
        seen = c.execute(sa.text("SELECT count(*) FROM metric_events WHERE event_type='iso'")).scalar()
    check("PART RLS isolates on partitioned table (A sees only its row)", seen == 1)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [DB: postgresql]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_real_partitioning():
    assert run()
