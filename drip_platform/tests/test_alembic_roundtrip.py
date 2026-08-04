"""
Alembic upgrade/downgrade round-trip test — not previously covered anywhere.

Every migration in this repo had only ever been exercised in the "upgrade"
direction (CI runs `alembic upgrade head` before the test suite). Running the
full round trip for real against a disposable Postgres caught a genuine bug:
d1a2b3c4e5f6_add_tenancy_and_rls.py's downgrade() tried to `DROP COLUMN
tenant_id` directly on partition CHILD tables (metric_events_default,
delivery_events_2026_07, etc.) -- Postgres rejects dropping an inherited
column from a partition child even with IF EXISTS, since the column only
really exists on the partitioned parent and the drop should cascade from
there. `pg_tables` has no defined row order, so this broke intermittently
depending on which table alembic happened to process first. Fixed in that
migration; this test exists so the class of bug (any migration that only
works in one direction) can't silently regress.

DESTRUCTIVE: `alembic downgrade base` drops every table. Guarded the same
way as test_tenancy_rls.py's RLS half -- requires DRIP_ALLOW_PG_TESTS=1,
which must only ever be set against a disposable database (CI's ephemeral
Postgres service container, or a throwaway local pgserver instance).

Run: DATABASE_URL=postgresql+psycopg2://... DRIP_ALLOW_PG_TESTS=1 \
     python tests/test_alembic_roundtrip.py
"""
import os
import sys
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def _alembic(args):
    r = subprocess.run([sys.executable, "-m", "alembic"] + args, cwd=_ROOT,
                       env=os.environ, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  $ alembic {' '.join(args)} -> exit {r.returncode}")
        print("  stdout:", r.stdout[-1500:])
        print("  stderr:", r.stderr[-1500:])
    return r.returncode


def run():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("… skipped (needs PostgreSQL; SQLite migrations are a no-op for the RLS revision)")
        return True
    if not os.environ.get("DRIP_ALLOW_PG_TESTS"):
        print("SKIP - destructive round trip guarded: set DRIP_ALLOW_PG_TESTS=1 on a "
              "DISPOSABLE test database (never your production drip DB).")
        return True

    check("alembic: upgrade head (1st pass) succeeds", _alembic(["upgrade", "head"]) == 0)
    check("alembic: downgrade to base succeeds", _alembic(["downgrade", "base"]) == 0)
    check("alembic: upgrade head (2nd pass, from empty) succeeds", _alembic(["upgrade", "head"]) == 0)

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_alembic_roundtrip():
    assert run()
