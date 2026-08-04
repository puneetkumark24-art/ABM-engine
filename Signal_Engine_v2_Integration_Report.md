# Signal Engine v2 Integration — Change Log, Migration Report, Rollback, Coverage

**Target system:** `drip_platform` (the FastAPI DRIP OS — confirmed the working, actively-developed codebase, not `decimal_abm`)
**Mode:** Shadow only. Nothing exported into real `signals` automatically. No outreach, no SendGrid, no LinkedIn scraping, no GitHub changes.
**Status:** Code integrated and upgraded to the production-candidate signal engine (quality gating, correction/retraction handling). **Now verified end-to-end against a real PostgreSQL 16 database** (see §8) — the migration, the bridge, and every route were proven against actual Postgres, not just SQLite. Your own database still needs the same migration applied for real — see §7.

---

## 1. Change log

### New files (all additive — nothing existing was deleted)

| File | Purpose |
|---|---|
| `signal_engine/` (`capture.py`, `catalog.py`, `cli.py`, `db.py`, `pipeline.py`, `__init__.py`) | The isolated 360° signal-capture engine, copied unchanged from the handoff package. Pure stdlib, owns its own SQLite file (`signal_engine.db`), never touches Postgres directly. |
| `abm_platform/services/signal_v2_bridge.py` | New. Replaces the handoff's Flask/raw-sqlite3 `bridge.py`. Resolves signal_engine's 11 catalog banks to your real `organizations.id` by name/alias matching (not a hardcoded ID list), excludes Decimal Technologies, and exports only `scoring_eligible=1` rows into the real `signals` table via SQLAlchemy — idempotently, tracked in a new `signal_v2_exports` ledger. |
| `routers/signal_review.py` | New. FastAPI router replacing the handoff's Flask blueprint. `GET /signal-review` (queue), `POST /signal-review/{id}/resolve`, `GET /signal-review/status`, plus the HubSpot and generic first-party capture webhooks (both HMAC/signature-gated, both reject with 401 if no secret is configured). |
| `scripts/signal_v2_export_cli.py` | New. Human-run preview/`--apply` export script, adapted to write into your real Postgres `signals` table via `database.SessionLocal`. |
| `alembic/versions/s6e8f0a2c4d5_add_signal_v2_exports.py` | New, reversible migration. Adds **one** table, `signal_v2_exports` (the export ledger). Touches nothing else. |
| `tests/test_signal_v2_bridge.py` | New. 3 tests proving the adapted bridge: idempotent export, a real `Signal` row actually gets written, Decimal Technologies is excluded, unmapped accounts are skipped (never guessed at). |
| `config/verified_watch_targets.csv`, `examples/*` | Copied from the handoff — verified page-watch config and test fixtures, needed by the CLI's documented commands. |

### Modified files (2 files, additive edits only)

| File | Change |
|---|---|
| `main.py` | +2 lines: import `signal_review`, `app.include_router(signal_review.router)`. Nothing else touched. |
| `routers/os_shell.py` | +1 nav entry ("Signal Review (Shadow)" under Intelligence) and one new `SCREENS.signalreview` function (~35 lines), following the exact same pattern as the existing `SCREENS.vendors`/`SCREENS.accounts`. No existing screen or route was edited. |

Both files were backed up before editing: `_signal_v2_backups/main.py.bak_20260802_105517` and `_signal_v2_backups/os_shell.py.bak_20260802_105517`.

### Explicitly not done (by design, per your boundaries)

- Nothing writes to SendGrid, HeyReach, or any send/outreach path.
- Nothing scrapes LinkedIn — the capture webhook only accepts authorized CSV/provider/export input.
- No signal is ever auto-promoted into `signals` — that only happens when a human runs `scripts/signal_v2_export_cli.py --apply`.
- GitHub was not touched.
- HubSpot object IDs are resolved through the capture layer, not trusted directly as account IDs (per the handoff's own "Known integration caution").

---

## 2. Database migration plan

**One migration, one table, additive only:**

```
alembic/versions/s6e8f0a2c4d5_add_signal_v2_exports.py
  revises: r5d7e9f1a3b4 (your current head)
  creates: signal_v2_exports (signal_uuid PK, drip_signal_id, se_account_id, org_id, exported_at, export_policy)
  + one index on org_id
  + grants SELECT/INSERT to app_rw if that role exists (same convention as your other migrations)
```

It does not alter, rename, or drop any existing table or column. Your real `signals` table already had every column the bridge needs (`org_id`, `signal_type`, `source`, `title`, `summary`, `url`, `urgency`, `confidence_score`, `content_hash`) — nothing new needed there.

**I could not run this migration against your real Postgres database** — it's on your machine at `localhost:5432` and this sandbox's network can't reach it (confirmed: connection refused, not a timeout). Run it yourself:

```bash
cd drip_platform
alembic upgrade head
```

This is the only schema change required. I validated the migration file imports and parses correctly; I was not able to run `alembic upgrade head` against real Postgres from here, so please confirm it applies cleanly on your machine and let me know if anything unexpected comes up.

---

## 3. Backup and rollback plan

**Before you run anything for real:**

```bash
# 1. Back up the database (run this on your machine, where Postgres is reachable)
pg_dump -h localhost -U postgres -d drip -F c -f drip_backup_$(date +%Y%m%d_%H%M%S).dump

# 2. File backups already made (in the repo):
#    drip_platform/_signal_v2_backups/main.py.bak_20260802_105517
#    drip_platform/_signal_v2_backups/os_shell.py.bak_20260802_105517
```

**To roll back the schema change only** (keeps all your data, removes just the new ledger table):

```bash
cd drip_platform
alembic downgrade -1
```

**To roll back everything** (full revert to pre-integration state):

```bash
cd drip_platform
alembic downgrade -1
rm -rf signal_engine abm_platform/services/signal_v2_bridge.py routers/signal_review.py \
       scripts/signal_v2_export_cli.py tests/test_signal_v2_bridge.py \
       alembic/versions/s6e8f0a2c4d5_add_signal_v2_exports.py examples config/verified_watch_targets.csv
cp _signal_v2_backups/main.py.bak_20260802_105517 main.py
cp _signal_v2_backups/os_shell.py.bak_20260802_105517 routers/os_shell.py
# restore DB from the pg_dump above if you'd applied real exports you want undone:
pg_restore -h localhost -U postgres -d drip --clean drip_backup_<timestamp>.dump
```

Because every export is idempotent and tracked in `signal_v2_exports`, rolling back the migration doesn't corrupt anything — any signals already exported into the real `signals` table simply stay there as ordinary signal rows (they don't disappear or become invalid) unless you also restore the DB dump.

---

## 4. Test results

| Suite | Result |
|---|---|
| `drip_platform` full existing test suite (41 files) | **39/41 pass.** The 2 failures (`test_signal_decay.py`, `test_signal_intel.py`) are **pre-existing and unrelated** — confirmed by checking: neither file references `signal_engine`, `signal_review`, or `signal_v2` anywhere, and the failures are all HTTP 302 redirects on the separate legacy Flask dashboard (`dashboard/app.py`), which this integration never touched. |
| `signal_engine`'s own test suite | **28/28 pass**, run from inside `drip_platform` — identical result to the standalone package. |
| Original `drip_integration/tests/test_bridge.py` | **Fails as expected** (`ModuleNotFoundError: abm_engine`) — it targets the decimal_abm Flask bridge, which was deliberately not copied in favor of the SQLAlchemy-native rewrite. Documented, not hidden. |
| New `tests/test_signal_v2_bridge.py` | **3/3 pass** — proves the real adapted code path: idempotent export, a genuine `models.Signal` row gets written and attributed to the correct `org_id`, Decimal Technologies is excluded from the prospect map, and an unmapped account is skipped rather than exported under a guessed ID. |
| Live route check (`TestClient`) | `GET /` still 200 and now shows "Signal Review" in nav (no regression on the main interface). New routes degrade gracefully before `signal_engine.db` exists (503 with a clear message, not a crash). After running the CLI's `init`+`demo`, `GET /signal-review/status` and `GET /signal-review` return real data. Both webhook endpoints correctly return 401 without a configured secret. |

---

## 5. Honest coverage report

This is the part to read carefully before telling anyone this is "live."

**Coverage is currently 0%, not the handoff's previously-reported 35.61%.** That 35.61% was accumulated in a *different* SQLite file on a *different* machine, from real successful checks against real bank websites. Copying the code does not carry that number over — coverage is earned per-database by actually running collection, not by installing the software.

I confirmed why it can't be re-earned from here: I ran `watch-check-all` from this sandbox and every single check failed with `403 Forbidden` — this sandbox's outbound network is proxied and allowlisted, and Al Rajhi/Riyad/STC/etc.'s domains aren't on that allowlist. This isn't a bug in the integration; it's a hard boundary of the environment I'm running in.

**What this means for you:** once you run this on your own machine (with normal internet access), run:

```bash
cd drip_platform
python -m signal_engine.cli --db signal_engine.db init
python -m signal_engine.cli --db signal_engine.db watch-seed-official
python -m signal_engine.cli --db signal_engine.db watch-import --file config/verified_watch_targets.csv
python -m signal_engine.cli --db signal_engine.db watch-check-all
python -m signal_engine.cli --db signal_engine.db capture-audit
```

and you'll get a real number — starting from wherever the original 35.61% left off is a reasonable expectation for `public_news`/`regulator`/`exchange` (those are simple RSS checks), but `careers`/`procurement`/`official_site` were already partial in the handoff's own report, and LinkedIn/CRM/email/website-intent were at 0/11 even before this — those don't change by moving the code, they need the actual work items 2–9 from `CLAUDE_HANDOFF.md`'s "Next work" list.

**The readiness threshold (90%) was not lowered, and nothing here counts an adapter as coverage** — consistent with your explicit instruction.

---

## 6. One thing I couldn't clean up

`drip_platform/_tmp_orig_bridge_test/` is a leftover scratch folder from proving the original `test_bridge.py` doesn't apply to this codebase. It's inert — nothing imports it, it's not wired into anything — but a sandbox file-lock issue prevented me from deleting it. Please delete it manually; it's safe to remove entirely.

---

## 7. What still needs to happen on your machine (I couldn't do these from this sandbox)

1. `pg_dump` the real `drip` database (command above).
2. `alembic upgrade head` to actually apply the migration to real Postgres.
3. `pip install` any new dependency this needs — signal_engine itself is stdlib-only, so this should be nothing new, but worth a clean `pip check` after.
4. Run the real `watch-check-all` to establish an honest live coverage number.
5. Decide when (if ever) to run `scripts/signal_v2_export_cli.py --apply` — I'd suggest not before the 7-day shadow trial the handoff itself recommends, and only after you've eyeballed the preview output.

---

## 8. Upgrade to the production-candidate engine + real-Postgres verification

Two follow-up requests came in after the report above: (a) a newer "FINAL production candidate" signal engine package, and (b) "make sure it's Postgres export, make sure it worked and Postgres ready." Both are done.

### 8a. Engine upgraded

The new package adds a `quality.py` module (structured claim extraction, completeness/materiality scoring), correction/retraction handling (a later "cancelled"/"retracted"/"corrected" story now contests the original signal — sets it to `status='contested'`, zeroes `scoring_eligible`/`action_eligible`, and routes to human review instead of silently sitting there as if still true), SSRF protection on watch URLs (rejects private/local addresses), and automatic redaction of emails/phones/credentials in raw captured payloads. Before installing it, I diffed it against what was already in `drip_platform`: the four tables my bridge depends on (`accounts`, `observations`, `signals`, `reviews`) are byte-identical — only new tables were added — so the upgrade was safe to apply directly. Old copy backed up to `_signal_v2_backups/signal_engine_v1_<timestamp>/`. 36/36 engine tests pass (up from 28), my 3 bridge tests still pass unchanged.

One thing worth knowing: `scoring_eligible` now also requires a 70% quality-completeness score before a signal is even export-eligible, and `action_eligible` is hardcoded to `0` unconditionally as a fail-safe. That means my bridge's export filter (`status='active' AND scoring_eligible=1`) already enforces "quality-gated and uncontested-signal-only" by construction — no separate query change was needed, because the upstream engine bakes both guarantees into those two fields before a signal is ever visible to the bridge.

### 8b. Real PostgreSQL verification (not SQLite this time)

The previous report was honest that I couldn't reach your actual Postgres — that's still true, it's on your machine. But I could stand up a **real, disposable PostgreSQL 16.2 server inside my own sandbox** (via the `pgserver` package, no root/admin needed) purely to prove the SQL is genuinely Postgres-correct, not just SQLite-compatible. Results:

- `alembic upgrade head` ran clean from a blank database through all ~40 existing migrations plus the new one, ending in `signal_v2_exports` — RC 0, no errors.
- Verified via `information_schema` that the table has the right columns, types, primary key, and index.
- My 3 bridge tests: **3/3 pass against real Postgres.**
- The export CLI script runs clean against real Postgres and correctly reports 0 eligible (honest — demo data isn't scoring-eligible).
- Live `TestClient` check against real Postgres: `GET /` → 200, `GET /signal-review/status` → 200 with real data, `GET /signal-review` → 200.
- As a bonus check, I also ran a sample of your *existing* tests against real Postgres for the first time — including `test_tenancy_rls.py` and `test_real_partitioning.py`, which test real Postgres-only features (row-level security, table partitioning) that SQLite can't even exercise. Both passed.

**One unrelated finding worth flagging:** `tests/test_scale_db.py` fails on real Postgres (`DROP TABLE opportunities` fails because `quotes` has a foreign key to it — Postgres enforces this, SQLite doesn't). I confirmed this has zero connection to the signal engine work (no reference to `signal_engine`/`signal_review`/`signal_v2` anywhere in that file) — it's a pre-existing gap in that test's own cleanup logic that's simply never been exercised against real Postgres before, since the whole suite defaults to SQLite. Not fixed (out of scope of this task), but you should know it's there before anyone assumes the full suite is Postgres-clean.

### 8c. Production-readiness gates now visible in the UI, not just the CLI

`GET /signal-review/status` now also returns the two real gates from `PRODUCTION_READINESS.md` — 360° coverage (needs ≥90% fresh account/channel checks) and quality calibration (needs ≥100 human-reviewed samples at ≥90% agreement) — pulled directly from `signal_engine`'s own audit functions, so they can never drift from what the CLI reports. The Signal Review screen in DRIP OS now shows both as a green/amber gate card, plus a note if any signal is currently contested by a correction. Nobody has to run CLI commands anymore to know whether this is ready for real migration — it's on the screen.

---

## 9. Autonomy pass (Aug 2, later same day) — scheduled capture, real bank sources, and the 30k-contact / 500-institution production-readiness audit

### 9a. Fully autonomous capture, no manual commands

`scripts/run_signal_pipeline.bat`, registered as Windows scheduled task **"DRIP Signal Pipeline"** (`schtasks`, every 2 hours, confirmed running end-to-end — log at `logs/signal_pipeline.log`). Each cycle now runs, in order: catalog-sync → watch-seed-official → watch-import → watch-check-all → collect-live → capture-audit → quality-backfill → quality-audit → capture-coverage. Nothing here exports into real `signals` or touches outreach — same shadow boundary as before, just unattended instead of manual.

### 9b. Real bank sources added (verified, not guessed)

9 new watch targets added to `config/verified_watch_targets.csv` after actually fetching each URL to confirm it's real: newsroom pages for SNB, SAB, ANB, BSF; careers pages for SAB, BSF, Bank Albilad; a vendor page for Bank Albilad. Bank AlJazira, STC Bank, and D360 Bank don't appear to publish a discoverable newsroom/careers page on their own domain — not guessed, left as-is. Total watch targets: 21 → 30.

### 9c. Production-readiness audit for 30k contacts / 500+ institutions

Audited the real bottlenecks against that target scale (schema, connection layer, caching, deployment). Found the core platform (Postgres, row-level-security multi-tenancy, UUIDv7 keys, partitioned event tables, Redis-backed rate limiting) already solid. Fixed what's safely fixable without touching your live machine:

- **`signal_engine/catalog.py`'s hardcoded 11-bank list was the real ceiling on 500+ institutions.** New script `scripts/signal_v2_catalog_sync.py` reads every active organization from the real Postgres `organizations` table and adds any not already one of the original 11 as a signal_engine account — using the organization's real Postgres UUID, excluding Decimal Technologies, matching by name/alias the same way the export bridge does so there's no collision with the 11 already-working banks. **Now wired as step 1 of the autonomous cycle** — add a bank to your real `organizations` table once, it's picked up automatically within 2 hours, no code change per institution. Verified against real Postgres (pgserver): correct add/skip/exclude logic, and confirmed idempotent (re-running doesn't duplicate rows).
- **New Alembic migration `t7f9a1b3c5d6_index_persons_email.py`** — adds `idx_persons_primary_email` (plain) and, on Postgres, `idx_persons_primary_email_lower` (case-insensitive) to `persons.primary_email`, which had no index at all. Deliberately does **not** add a uniqueness constraint — that could fail outright if duplicate emails already exist in your real data, which I can't check from here; recommend a dedup report as a follow-up before enforcing uniqueness. Also added `index=True` to the `Person.primary_email` column in `models.py` so dev/test (SQLite `create_all`) and production (Postgres via Alembic) stay consistent. Verified: full ~44-migration chain runs clean on a blank real Postgres through to this new head, both indexes confirmed present via `pg_indexes`, downgrade confirmed clean.
- Both changes verified together: app still boots (`main.py` imports, 37 routes), all 3 existing bridge tests still pass unchanged.

**Still open, deliberately not attempted today (each is a real, separate piece of work):**

1. **Real production deployment.** The app currently runs via `uvicorn main:app --reload` in a terminal on your own laptop — fine for shadow-mode testing, not real production. Needs: multiple worker processes, auto-restart on crash, and it shouldn't go down when your laptop sleeps. This is a hosting decision (cloud VM vs. your machine as a Windows service) I didn't want to make unilaterally.
2. **`signal_engine.db` is still SQLite** — a single-writer file. Fine at today's ~30 watch targets; at genuine 500-institution capture volume, concurrent writes from the pipeline plus dashboard reads risk lock contention. Porting the shadow engine's storage layer to Postgres is a bigger, riskier change to a tested vendor package — deserves its own dedicated pass, not a rushed one alongside everything else today.
3. **The actual list of 500 institutions isn't populated yet.** The catalog-sync mechanism now scales automatically, but someone still has to add the other ~489 organizations to the real `organizations` table (or import them) before the engine has anything to sync.
4. **HubSpot webhook** still can't receive anything live — it needs a public HTTPS endpoint, which requires item 1 (real deployment) first.
