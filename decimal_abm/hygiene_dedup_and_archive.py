"""
hygiene_dedup_and_archive.py
────────────────────────────
Phase 2e data hygiene, per MASTER_CONSOLIDATION_PLAN.md Section 7 action #2.

Two things, both additive/non-destructive (archive, never drop — Golden Rule):

1. Dedup `signals`: 178 of 264 rows share a URL with an earlier row (57 unique
   URLs among 235 URL-populated rows; 29 rows have no URL and are left alone —
   no safe way to dedupe those). For each duplicate URL, keeps the row with the
   lowest id (earliest insert) in `signals`, moves the rest verbatim into a new
   `signals_archived_duplicates` table (nothing is deleted from the database,
   just relocated), then adds a partial UNIQUE index so this can't recur.

2. Archive tables confirmed DEAD by actually grepping the live code path
   (`abm_engine/dashboard/app.py` + `abm_engine/database/db.py`, the modules
   `run_dashboard.py`/`__main__.py` actually import), not by trusting a prior
   report's table list at face value.

   IMPORTANT CORRECTION vs. an earlier report (DRIP_Phase1_System_Discovery_Report.md):
   that report labeled draft_messages/touch_records/news_items/score_breakdowns/
   engagement_events/kpi_snapshots/research_cache as "orphaned V8 tables" superseded
   by drafts/touch_log. Grepping the actual live code shows the OPPOSITE: db.py's
   real CRUD functions (save_draft, get_pending_drafts, save_touch, get_touch_history,
   save_news_item, save_score_breakdown, save_engagement, upsert_kpi_snapshot, ...)
   read/write draft_messages/touch_records/news_items/score_breakdowns/
   engagement_events/kpi_snapshots — these are LIVE, not orphaned. Archiving them
   would have broken decimal_abm's running dashboard and this session's own Phase 1
   sequencing work. `drafts` and `touch_log` are the ones with zero live callers —
   referenced only by `abm_engine/abm_engine/dashboard/app.py` (a stray nested
   duplicate package nothing imports — confirmed by grep, zero importers) and
   `abm_engine/dashboard/app_sqlite_backup.py` (explicitly named as a backup, not
   wired into `run_dashboard.py`/`__main__.py`). Those two — `drafts` and
   `touch_log` (1 row each: a real sent draft to contact_id=1, dated
   2026-06-03, presumably written by that dead/nested code path at some
   point) — are what this script actually archives. Renaming preserves that
   row (Golden Rule: archive, never drop); it's just moved somewhere nothing
   live reads from today. `research_cache` (0 rows, defined in the schema
   but no CRUD function anywhere) is archived too since nothing reads or
   writes it today.

   One more check performed before applying: `engine_scheduler.py` (repo root)
   also reads/writes `drafts`/`touch_log` directly via raw SQL and is labeled
   "PRODUCTION-GRADE" in its own header, which looked like a live counter-example.
   Confirmed via `abm_engine/README.md` and `PHASE_0_CHANGES.md` (both predate
   this session) that `engine_scheduler.py` is explicitly superseded and
   documented as "don't run alongside" the CLI/orchestrator path this session
   built on — so it does not count as a live caller.

Usage:
    python hygiene_dedup_and_archive.py --dry-run    # run against a temp copy, report only
    python hygiene_dedup_and_archive.py --apply       # run for real against abm_engine.db
                                                       # (writes a timestamped backup first)
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LIVE_DB = REPO_ROOT / "abm_engine.db"

# CORRECTED list (see docstring above). These are the tables with zero live
# callers in abm_engine/database/db.py + abm_engine/dashboard/app.py + core/*.
# draft_messages/touch_records/news_items/score_breakdowns/engagement_events/
# kpi_snapshots are LIVE and must NOT be archived — removed from this list
# after direct grep verification against the running code.
DEAD_TABLES = [
    "drafts", "touch_log", "research_cache",
]


def run(db_path: Path, apply: bool) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    print(f"\n=== Running against: {db_path} ({'LIVE' if apply else 'temp copy / dry-run'}) ===")

    # ── 1. Dedup signals ──────────────────────────────────────────────────────
    existing_tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    dup_urls = conn.execute("""
        SELECT url, COUNT(*) c FROM signals
        WHERE url IS NOT NULL AND url != ''
        GROUP BY url HAVING c > 1
    """).fetchall()
    dup_row_count = sum(r["c"] - 1 for r in dup_urls)  # keep 1 per group, archive the rest
    print(f"signals: {total} total rows, {len(dup_urls)} duplicated URLs, "
          f"{dup_row_count} duplicate rows to archive")

    if "signals_archived_duplicates" not in existing_tables:
        conn.execute("""
            CREATE TABLE signals_archived_duplicates AS
            SELECT * FROM signals WHERE 0
        """)
        conn.execute("ALTER TABLE signals_archived_duplicates ADD COLUMN archived_at TEXT")
        conn.execute("ALTER TABLE signals_archived_duplicates ADD COLUMN archived_reason TEXT")

    moved = 0
    for r in dup_urls:
        url = r["url"]
        rows = conn.execute(
            "SELECT * FROM signals WHERE url=? ORDER BY id ASC", (url,)
        ).fetchall()
        keeper = rows[0]
        for dup in rows[1:]:
            cols = dup.keys()
            placeholders = ",".join("?" * len(cols))
            colnames = ",".join(cols)
            conn.execute(
                f"INSERT INTO signals_archived_duplicates ({colnames}, archived_at, archived_reason) "
                f"VALUES ({placeholders}, datetime('now'), ?)",
                (*[dup[c] for c in cols], f"duplicate of signals.id={keeper['id']} (same url)")
            )
            conn.execute("DELETE FROM signals WHERE id=?", (dup["id"],))
            moved += 1
    print(f"  -> moved {moved} duplicate rows into signals_archived_duplicates "
          f"(kept the earliest-id row per url in signals)")

    # Prevent recurrence: partial unique index (NULL/empty urls are exempt)
    conn.execute("DROP INDEX IF EXISTS idx_signals_url_unique")
    conn.execute("""
        CREATE UNIQUE INDEX idx_signals_url_unique ON signals(url)
        WHERE url IS NOT NULL AND url != ''
    """)
    print("  -> added partial UNIQUE index on signals.url (NULL/empty exempt)")

    remaining = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    remaining_dup_check = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT url FROM signals WHERE url IS NOT NULL AND url != '' GROUP BY url HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    print(f"  -> signals now has {remaining} rows, {remaining_dup_check} remaining duplicate-url groups "
          f"(expect 0)")

    # ── 2. Archive genuinely dead tables (verified via grep, not assumed) ─────
    for t in DEAD_TABLES:
        if t not in existing_tables:
            print(f"  (skip) {t}: not present")
            continue
        archived_name = f"archived_dead_{t}"
        if archived_name in existing_tables:
            print(f"  (skip) {t}: already archived as {archived_name}")
            continue
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.execute(f"ALTER TABLE {t} RENAME TO {archived_name}")
        print(f"  -> archived {t} ({n} rows) -> {archived_name}")

    conn.commit()

    # ── Report ─────────────────────────────────────────────────────────────────
    final_tables = sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall())
    print(f"\nFinal table list ({len(final_tables)}): {final_tables}")
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="Run against a disposable temp copy only")
    grp.add_argument("--apply", action="store_true", help="Run for real against the live abm_engine.db")
    args = ap.parse_args()

    if not LIVE_DB.exists():
        print(f"FAIL: {LIVE_DB} not found — run this from decimal_abm/.")
        sys.exit(1)

    if arg