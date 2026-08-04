"""signal_v2_catalog_sync.py -- removes the "hardcoded to 11 banks" ceiling
that blocks the signal engine from scaling to hundreds of institutions.

Problem: signal_engine/catalog.py's ACCOUNTS list is a static Python list of
11 Saudi banks. Every signal_engine command (init/demo/collect-live) reseeds
exactly those 11 and nothing else -- so today, no matter how many
organizations exist in the real DRIP `organizations` Postgres table, the
signal engine only ever knows about 11 of them.

Fix: this script is the bridge. It reads every active Organization from the
REAL Postgres database (the same one drip_platform's API reads), and for any
organization NOT already one of the original 11 catalog banks, adds it as a
signal_engine account -- using the organization's own real Postgres UUID as
the signal_engine account id (not a hand-picked short code, since there's no
human curating 500 short codes).

Why this is safe / additive, matching every boundary from the original
integration:
  - The original 11 banks are left completely alone. This script only adds
    accounts for organizations NOT matched to the existing catalog (by exact
    name/alias match, same logic abm_platform/services/signal_v2_bridge.py
    uses to route exports) -- so there is no duplicate-id collision and no
    risk to the already-tested export bridge for those 11.
  - Decimal Technologies is excluded, same as the bridge.
  - Only reads Postgres; only writes to the isolated signal_engine.db shadow
    SQLite file. Never writes to the real `signals`/`organizations` tables.
  - Idempotent: safe to run every pipeline cycle (INSERT ... ON CONFLICT DO
    UPDATE inside Pipeline.add_account), so as the real organizations table
    grows toward 500 institutions, each new one is picked up automatically
    on the next scheduled run -- no manual code change needed per bank.

Run manually:
    python scripts/signal_v2_catalog_sync.py
Or (recommended) it's already wired into scripts/run_signal_pipeline.bat as
an automatic step, so this happens on its own every 2 hours.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import SessionLocal  # noqa: E402
import models  # noqa: E402
from signal_engine.catalog import ACCOUNTS as CATALOG_ACCOUNTS  # noqa: E402
from signal_engine.db import connect, initialize  # noqa: E402
from signal_engine.pipeline import Pipeline  # noqa: E402

EXCLUDED_ACCOUNT_NAMES = {"decimal technologies", "decimal"}


def _covered_names() -> set[str]:
    """Every name/alias already owned by the static 11-bank catalog --
    matches organizations against these to decide "already covered" the same
    way signal_v2_bridge.build_account_map() does, so the two stay consistent."""
    covered = set()
    for acct in CATALOG_ACCOUNTS:
        for cand in [acct["name"], *acct.get("aliases", [])]:
            if cand:
                covered.add(cand.strip().lower())
    return covered


def _domain_from_website(website: str | None) -> str | None:
    if not website:
        return None
    url = website if "://" in website else f"https://{website}"
    host = urlsplit(url).hostname
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def _signal_db_path() -> str:
    # Must match signal_engine.cli.DEFAULT_DB (work/signal_engine.db) -- see
    # routers/signal_review.py for the full explanation of why this matters.
    from signal_engine.cli import DEFAULT_DB
    return os.environ.get("SIGNAL_V2_DB", str(DEFAULT_DB))


def sync() -> dict:
    covered = _covered_names()
    db = SessionLocal()
    added, skipped_covered, skipped_excluded, skipped_no_domain = [], [], [], []
    try:
        orgs = db.query(models.Organization).filter(models.Organization.is_active == True).all()  # noqa: E712
        con = connect(_signal_db_path())
        initialize(con)
        pipe = Pipeline(con)
        existing_ids = {r[0] for r in con.execute("SELECT id FROM accounts")}
        new_ids, updated_ids = [], []
        for org in orgs:
            candidates = [org.canonical_name, org.short_name, *(org.aliases or [])]
            candidates = [c for c in candidates if c]
            norm_candidates = {c.strip().lower() for c in candidates}
            if norm_candidates & EXCLUDED_ACCOUNT_NAMES:
                skipped_excluded.append(org.canonical_name)
                continue
            if norm_candidates & covered:
                skipped_covered.append(org.canonical_name)
                continue
            domain = _domain_from_website(org.website)
            if not domain:
                skipped_no_domain.append(org.canonical_name)
                continue
            aliases = [c for c in candidates if c != org.canonical_name]
            pipe.add_account(org.id, org.canonical_name, aliases, [domain], [])
            entry = {"org_id": org.id, "name": org.canonical_name, "domain": domain}
            added.append(entry)
            (new_ids if org.id not in existing_ids else updated_ids).append(org.id)
        con.close()
    finally:
        db.close()
    return {
        "synced_beyond_static_catalog": len(added), "synced_accounts": added,
        "newly_added_this_run": len(new_ids), "already_present_refreshed": len(updated_ids),
        "skipped_already_in_catalog": len(skipped_covered),
        "skipped_excluded": len(skipped_excluded),
        "skipped_no_website_domain": skipped_no_domain,
    }


if __name__ == "__main__":
    print(json.dumps(sync(), indent=2, ensure_ascii=False))
