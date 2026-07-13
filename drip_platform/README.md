# DRIP Platform — Phase 2-6 Vertical Slice

Working code produced from the Phase 1 discovery findings (see
`DRIP_Phase1_System_Discovery_Report.md`). This is a real, tested vertical
slice — database → ETL → API → scoring — not a mockup. It reconciles the
three prior artifacts found on disk (decimal_abm, the ABM Business Logic
Bible, brip_dashboard) rather than starting over.

## What's here

| Layer | File(s) | Status |
|---|---|---|
| Schema (Phase 2) | `models.py`, `alembic/versions/*_initial_drip_schema.py` | Built + verified |
| ETL (Phase 3) | `etl/migrate_from_decimal_abm.py`, `etl/documented_contacts_seed.py` | Built + verified against real data |
| API (Phase 4) | `main.py`, `routers/*.py`, `schemas.py` | Built + verified (organizations, persons, signals, opportunities) |
| Scoring / AI (Phase 6, partial) | `scoring.py`, `modifiers.json` | Built + verified (T-SCORE-1, T-SCORE-2 pass) |
| Dashboard (Phase 5) | Not built this pass | See "Not done" below |

## Verified in this session (sandboxed, SQLite fallback — see caveat below)

```
pytest tests/test_scoring.py -v          # 4/4 pass, incl. T-SCORE-1 = 46.8 exactly
python etl/migrate_from_decimal_abm.py --sqlite-path <path to abm_engine.db>
  -> accounts_created: 25, products_created: 5, signals_created: 86
     (178 duplicate-URL signals correctly skipped — see note below)
     documented_contacts: 20 persons across 3 new + existing organizations
uvicorn main:app  ->  GET /organizations?search=Al%20Rajhi  -> 200, correct data
                       GET /organizations/{id}/persons      -> 200, 8 real contacts incl. Abid Shakeel (CSO, Champion)
```

## Run it for real, against your Postgres — ONE COMMAND

`.env` is already filled in with your real Postgres credentials (same
host/user/password as `decimal_abm/abm_engine/.env`, pointed at a fresh
`drip` database so it never collides with `abm_engine` or `brip`).

**Windows:** double-click `setup_drip.bat` (or run it from a terminal).
**macOS/Linux:** `./setup_drip.sh`

That single script: creates the `drip` database if it doesn't exist, runs
`alembic upgrade head` to build every table, runs the ETL migration against
your live `decimal_abm/abm_engine.db`, then prints the exact command to
start the API. It's idempotent — safe to re-run any time (e.g. after you
add new signals to decimal_abm) to refresh `drip` with the latest data.

Manual equivalent, if you'd rather run each step yourself:

```bash
pip install -r requirements.txt
python setup_and_run.py
```

Or fully manual:

```bash
pip install -r requirements.txt
createdb drip                                    # on your Postgres instance
export DATABASE_URL="postgresql+psycopg2://postgres:<password>@localhost:5432/drip"
alembic upgrade head                             # creates all tables
python etl/migrate_from_decimal_abm.py --sqlite-path "C:\Users\Puneet\Desktop\decimal_abm\abm_engine.db"
uvicorn main:app --reload                        # API at http://127.0.0.1:8000/docs
```

**What I could not do from this sandbox:** this Postgres instance lives on
your Windows machine at `localhost:5432` — the sandboxed Linux environment
this code was built and tested in has no network path to it, and no root
access to install a local Postgres server to fully rehearse the exact
command. `setup_and_run.py` was tested for correct behavior when Postgres
is unreachable (clean error message, no stack trace) but the actual
create-database-and-migrate path against a live server has not been run by
me. Run it and tell me what breaks, if anything does.

**Caveat on the SQLite fallback:** this sandbox has no Postgres server (no root
access to install one), so verification above ran against SQLite. All models
use portable SQLAlchemy types (`String(36)` UUIDs, generic `JSON`) specifically
so they run unchanged on Postgres — but the Postgres path itself has not been
executed. Run `alembic upgrade head` against your real `DATABASE_URL` and
re-run the ETL as the first thing you do, before trusting this further.

## Data quality finding surfaced by the ETL run

Of 264 signal rows in the live decimal_abm database, only 86 have a unique
URL — 178 are duplicates. This means the RSS signal scanner's dedup logic in
`decimal_abm/signals/monitor.py` is not actually preventing duplicate
inserts in production, even though `schema_v2.sql` has a `UNIQUE` constraint
on `signals.url`. Worth checking why the live table has entries the schema
should have rejected (likely: constraint added after those rows already
existed, or the constraint was on a different column in an earlier version).

## Not done in this pass (honest scope statement)

Given the instruction to move fast, this vertical slice deliberately does
NOT include, and would need dedicated follow-up work:

- **Document Intelligence / OCR** (PRD §14) — genuinely greenfield, nothing
  to reuse from prior artifacts. Not started.
- **Identity Resolution Engine** (PRD §16) beyond exact-name-match dedup in
  the ETL script. Fuzzy matching, confidence scoring, and merge workflows
  are not built.
- **Dashboard** (PRD §17) — `brip_dashboard`'s Flask templates exist and are
  a reasonable starting point (see Phase 1 report §3) but haven't been
  rewired to this schema/API yet.
- **AI drafting** — `decimal_abm/agents/writer.py` has working Gemini
  integration; it hasn't been ported to call this API instead of the old
  SQLite layer.
- **Autonomy Ladder (A0-A5), Trust_Capital_Ledger, Rule_Registry as a live
  table** (Bible Tier 3/4) — `modifiers.json` is the seed content for
  Rule_Registry per the Bible's own recommendation, but it's a static file
  here, not a governed, versioned database table yet.
- **Auth/authorization on the API** — no auth is wired in yet; every
  endpoint is open. Do not expose this outside localhost as-is.
- **Bulk upload, pagination cursors, materialized views, table
  partitioning** (PRD §17-19) — not built; current scale (25 orgs) doesn't
  need them yet, but they're absent, not deferred-and-stubbed.

## Design decisions made without asking (flagging per Golden Rules)

- Adopted `brip_dashboard`'s universal `organizations` shape over the
  Bible's prospect-only `Account`, per the Phase 1 report's Section 6
  recommendation and your "full rebuild as specified" answer.
- Kept the Bible's exact scoring formula and modifier values verbatim
  (Build Artifact 1) rather than approximating — this is copied, not
  redesigned, so any Rule_Registry override should edit `modifiers.json`,
  not the formula in `scoring.py`.
- The 20 documented contacts came from project memory notes, not from any
  file on disk — transcribed as-is with `email_confidence="Unknown"` since
  no verified emails exist in the source notes. Do not treat these as
  outreach-ready; they need enrichment before any contact attempt.
