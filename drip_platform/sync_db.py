"""
sync_db.py — bring an EXISTING drip database up to the current code's schema,
additively and idempotently. Built for Puneet's local Postgres `drip` DB, which
was created by the app's create_all() (so the alembic chain can't be applied
from revision zero — CREATE TABLE collides with tables that already exist).

What it does (safe to run repeatedly; never drops or rewrites data):
  1. CREATE any table the models define that the DB doesn't have.
  2. ALTER TABLE ADD COLUMN (nullable) for any model column missing in the DB
     — e.g. signals.content_hash, opportunities.amount_minor.
  3. Backfill opportunities.amount_minor from the legacy free-text
     estimated_value where NULL.
  4. Stamp alembic at head so future `alembic upgrade head` runs cleanly.

Run:  python sync_db.py          (uses DATABASE_URL / .env)
"""
from __future__ import annotations
import re
import sys

import sqlalchemy as sa

from database import Base, engine, SessionLocal

# import every model module so Base.metadata is complete
import models            # noqa: F401
import models_ext        # noqa: F401
import models_tenant     # noqa: F401
import models_jobs       # noqa: F401
import models_p10        # noqa: F401
import models_p11        # noqa: F401
import models_p12        # noqa: F401
import models_audit      # noqa: F401
import models_crm2       # noqa: F401
import models_s3         # noqa: F401
import models_s6         # noqa: F401
import models_s8         # noqa: F401

_NUM = re.compile(r"[\d.]+")


def _to_minor(txt):
    if not txt:
        return None
    t = str(txt).lower().replace(",", "")
    m = _NUM.search(t)
    if not m:
        return None
    val = float(m.group())
    if "m" in t or "million" in t:
        val *= 1_000_000
    elif "k" in t:
        val *= 1_000
    return int(round(val * 100))


def main() -> int:
    insp = sa.inspect(engine)
    existing_tables = set(insp.get_table_names())
    print(f"DB: {engine.url.render_as_string(hide_password=True)}")
    print(f"existing tables: {len(existing_tables)}")

    # 1. create missing tables
    created = []
    for tname, table in Base.metadata.tables.items():
        if tname not in existing_tables:
            table.create(bind=engine, checkfirst=True)
            created.append(tname)
    print(f"tables created: {created or 'none'}")

    # 2. add missing columns (nullable, additive only)
    added = []
    insp = sa.inspect(engine)  # refresh
    with engine.begin() as conn:
        for tname, table in Base.metadata.tables.items():
            if tname not in existing_tables:
                continue  # just created — already complete
            have = {c["name"] for c in insp.get_columns(tname)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                conn.execute(sa.text(
                    f'ALTER TABLE "{tname}" ADD COLUMN "{col.name}" {coltype} NULL'))
                added.append(f"{tname}.{col.name}")
    print(f"columns added: {added or 'none'}")

    # 3. backfill amount_minor from legacy free-text estimated_value
    backfilled = 0
    with engine.begin() as conn:
        rows = conn.execute(sa.text(
            "SELECT id, estimated_value FROM opportunities "
            "WHERE amount_minor IS NULL AND estimated_value IS NOT NULL")).fetchall()
        for oid, ev in rows:
            minor = _to_minor(ev)
            if minor is not None:
                conn.execute(sa.text(
                    "UPDATE opportunities SET amount_minor=:m WHERE id=:i"),
                    {"m": minor, "i": oid})
                backfilled += 1
    print(f"amount_minor backfilled: {backfilled}")

    # 4. stamp alembic head so future migrations apply incrementally
    try:
        from alembic.config import Config
        from alembic import command
        import os
        cfg = Config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini"))
        command.stamp(cfg, "head")
        print("alembic: stamped head")
    except Exception as e:  # noqa: BLE001
        print(f"alembic stamp skipped: {e}")

    # sanity probe: the two columns that were breaking the dashboard
    insp = sa.inspect(engine)
    sig_cols = {c["name"] for c in insp.get_columns("signals")}
    opp_cols = {c["name"] for c in insp.get_columns("opportunities")}
    ok = "content_hash" in sig_cols and "amount_minor" in opp_cols
    print(f"verify: signals.content_hash={'OK' if 'content_hash' in sig_cols else 'MISSING'}, "
          f"opportunities.amount_minor={'OK' if 'amount_minor' in opp_cols else 'MISSING'}")
    print("SYNC COMPLETE" if ok else "SYNC INCOMPLETE — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
