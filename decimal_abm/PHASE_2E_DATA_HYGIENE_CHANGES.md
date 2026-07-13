# Phase 2e — Data Hygiene (decimal_abm)

Per `MASTER_CONSOLIDATION_PLAN.md` Section 7, action #2: "Fix the 178
duplicate signals + retire the orphaned decimal_abm tables." Applied to the
live `abm_engine.db` on 2026-07-13. Script: `hygiene_dedup_and_archive.py`
(repo root, `decimal_abm/`).

## What was actually wrong

`signals` had 264 rows but only 86 unique URLs — 178 rows were exact
duplicates of an earlier row's URL, despite `schema_v2.sql` having a
`UNIQUE` constraint on `signals.url` (the constraint was evidently added
after these rows already existed, or applied to a different column in an
earlier schema version — not re-diagnosed further since the fix doesn't
depend on knowing which).

Separately, a prior session's `DRIP_Phase1_System_Discovery_Report.md`
claimed 7 tables (`draft_messages`, `touch_records`, `news_items`,
`score_breakdowns`, `engagement_events`, `kpi_snapshots`, `research_cache`)
were dead "V8-era" tables superseded by `drafts`/`touch_log`. **This claim
was wrong** — verified by grepping the actual live code before touching
anything:

- `draft_messages`/`touch_records`/etc. are read and written by real,
  currently-used functions in `abm_engine/database/db.py`
  (`save_draft`, `get_pending_drafts`, `get_approved_unsent_drafts`, `save_touch`,
  `get_touch_history`, ...) and `abm_engine/core/orchestrator.py` — including
  functions this project's own Phase 1 work (sequence engine) edited directly.
  Archiving these would have broken the running dashboard and the Phase 1
  sequencing work.
- `drafts`/`touch_log` looked "live" too, because `engine_scheduler.py`
  (repo root, labeled "PRODUCTION-GRADE" in its own header) reads/writes them
  directly via raw SQL. But `abm_engine/README.md` and this project's own
  `PHASE_0_CHANGES.md` (both predate this session) explicitly document
  `engine_scheduler.py` as **superseded** and say not to run it alongside the
  CLI/orchestrator path — so it doesn't count as a live caller. The only
  actual callers of `drafts`/`touch_log` today are a stray nested duplicate
  package (`abm_engine/abm_engine/dashboard/app.py` — nothing imports it,
  confirmed by grep) and a file explicitly named as a backup
  (`abm_engine/dashboard/app_sqlite_backup.py`).

## What was done (archive, never drop — Golden Rule)

1. **Deduped `signals`**: for each of the 31 duplicate URLs, kept the
   lowest-id (earliest) row in `signals` and moved the other 178 rows verbatim
   into a new `signals_archived_duplicates` table (with `archived_at` /
   `archived_reason` columns added). Nothing deleted — every duplicate row
   still exists, just relocated. Added a partial `UNIQUE` index
   (`idx_signals_url_unique`, exempting NULL/empty URLs) so this can't recur.
   Result: `signals` 264 → 86 rows, 0 remaining duplicate-URL groups.

2. **Archived the 3 genuinely dead tables** — `drafts` (1 row), `touch_log`
   (1 row), `research_cache` (0 rows) — by renaming them to
   `archived_dead_drafts`, `archived_dead_touch_log`,
   `archived_dead_research_cache` (SQL rename, data fully preserved,
   nothing dropped). The 1 row each in `drafts`/`touch_log` was a real sent
   draft to contact_id=1 dated 2026-06-03.

3. **Did NOT touch** `draft_messages`, `touch_records`, `news_items`,
   `score_breakdowns`, `engagement_events`, `kpi_snapshots` — confirmed live,
   left exactly as they were.

## Verification performed

- Dry run against a disposable temp copy first (`--dry-run`), inspected
  output, confirmed exact expected counts before touching anything real.
- Re-ran the same dry run against a *fresh* temp copy of the real live file
  immediately before applying, to rule out drift between the two.
- `python -m py_compile` clean on the script.
- A timestamped backup of the live `abm_engine.db` was written to
  `decimal_abm/backups/pre_hygiene_20260713_180918.db` before the real run —
  full rollback path if anything downstream looks wrong.
- Post-apply, confirmed the live table list has 23 tables, with
  `draft_messages`/`touch_records`/`news_items`/`score_breakdowns`/
  `engagement_events`/`kpi_snapshots` all still present and untouched.

## What this deliberately does NOT do

- Does not delete the stray nested `abm_engine/abm_engine/` duplicate
  package directory — nothing imports it (confirmed dead), but this
  session's sandbox cannot delete files/folders in this mounted location.
  Recommend removing it locally the next time you're in the folder; it is
  not wired into anything, so removing it changes nothing at runtime.
- Does not touch `engine_scheduler.py` itself, despite it being superseded —
  out of scope for a data-hygiene pass; a separate decision if you want it
  deleted/archived as dead code.
- Does not re-run or repair `signals/monitor.py`'s dedup logic that let the
  178 duplicates in to begin with — the partial unique index now blocks
  future duplicate inserts at the DB layer regardless, but the underlying
  application-level dedup bug in the RSS scanner hasn't been separately
  diagnosed.
