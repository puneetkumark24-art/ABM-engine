# Phase 10 — End-to-End Engine + Verified on Real PostgreSQL

The two priority gaps from the match report (engagement loop, Pipeline Engine),
the remaining CRM gaps (merge engine, AI timeline), one orchestrator tick that
runs the whole engine, **and the entire platform proven against a real
PostgreSQL 16.2 server** — full migration chain + all three test suites.

Registry after this phase: **21 LIVE · 5 PARTIAL** (of 26).

## Test gate — everything green on BOTH databases

| Suite | SQLite | PostgreSQL 16.2 |
|---|---|---|
| test_sequence_engine.py | 30/30 | **30/30** |
| test_platform_services.py | 53/53 | **53/53** |
| test_engine_e2e.py | 30/30 | **30/30** |
| Alembic chain (15 migrations → `a7c4e2f1d8b3`) | n/a | **65 tables, clean** |

## What was built

### 1 · Engagement loop — the Mailchimp wire, closed
`abm_platform/services/engagement.py`: delivery events + LinkedIn actions +
form submissions + replies → `person_engagement` rollup (0–1) → org
reachability (0–20: coverage + engagement) → full dimension recompute →
`account_scores` row → **HOT/WARM/COLD re-tier on `AccountIntelligence`** →
`score.updated` / `account.tiered` events. Bounces subtract. The loop the
original bug history flagged as never enforced now moves the score.

### 2 · Pipeline Engine — the HubSpot gap, closed
`models_p10.py` + `abm_platform/services/pipeline.py`: configurable pipelines
with ordered stages (probability, rotting_days, won/lost flags), governed deal
placement via `opportunity_stage_links` (the `opportunities` table untouched —
purely additive link table), stage moves with history + illegal-move rejection,
**weighted forecast** (parses free-text SAR/M/k amounts), and health flags:
stalled, single-threaded, hygiene.

### 3 · Merge engine
`merge.py`: re-points every association (activities, drafts, messages, LinkedIn
actions, touches, form submissions, relationships both directions; unique-
constrained tables handled slot-by-slot), fills keeper blanks, strictest safety
flags win (do_not_contact / consent denied / replied), loser **deactivated
never deleted**, merge candidates resolved, fully audited.

### 4 · AI Timeline assembler
`timeline.py`: one chronologically-merged history per person/org across
activities, sequence events, delivery events, LinkedIn, forms, AI generations,
touches, signals.

### 5 · The end-to-end orchestrator
`orchestrator.py run_tick()` — one call runs the engine:
```
due sequence steps (compliance + KSA window)
  → AI draft (anonymized, QC'd; c-suite HELD for human — verified)
  → Draft record → dry-run delivery (idempotent, evented)
  → sequence advance → attribution touch → analytics event
  → per touched org: engagement rollup → rescore → re-tier
```
Exposed as `POST /engine/tick`. Wire it to the scheduler for the autonomous
loop; the three hard stops (c-suite, compliance gates, dry-run-only transport)
are enforced in the services and cannot be bypassed from the API.

## PostgreSQL verification (this session, real server)

A genuine PostgreSQL 16.2 instance was run (user-space `pgserver`), and:
1. `alembic upgrade head` executed the **full 15-migration chain** cleanly → 65 tables.
2. All three suites passed against it (113/113).
3. **It caught a real bug SQLite hides:** composite message ids
   (`seq-<uuid>-<step>`) exceeded `VARCHAR(36)` — Postgres enforces lengths.
   Fixed in `models_ext.py` (→ `String(80)`) + corrective migration
   `a7c4e2f1d8b3` (Postgres-only ALTER).

## Apply on your machine (your real Postgres `drip` DB)

```bash
cd drip_platform
alembic upgrade head       # runs d4e8b1c5a7f9, f0a3d6e9c1b7, a7c4e2f1d8b3
python tests/test_sequence_engine.py      # 30/30
python tests/test_platform_services.py    # 53/53
python tests/test_engine_e2e.py           # 30/30
uvicorn main:app --reload
# then: POST /engine/tick  (dry-run — safe), GET /engine/pipelines/... , /engine/timeline/...
```

## New API surface

```
POST /engine/tick                          the whole loop, one call
POST /engine/engagement/rollup/{org_id}    rollup + rescore + re-tier one org
POST /engine/pipelines                     create pipeline (+ default 6 stages)
POST /engine/pipelines/assign              attach a deal
POST /engine/deals/{id}/move               guarded stage move (history kept)
GET  /engine/pipelines/{id}/forecast       weighted + best-case
GET  /engine/pipelines/{id}/health         stalled / single-threaded / hygiene
POST /engine/merge/persons                 merge duplicates (history preserved)
GET  /engine/timeline/person/{id}          unified AI timeline
GET  /engine/timeline/org/{id}             org-wide timeline incl. signals
```

## Files
`models_p10.py` · `alembic/versions/f0a3d6e9c1b7_…` · `alembic/versions/a7c4e2f1d8b3_…`
· `abm_platform/services/{engagement,pipeline,merge,timeline,orchestrator}.py`
· `routers/engine_e2e.py` · `tests/test_engine_e2e.py` · registry: 19 → LIVE
· `models_ext.py` (message_id width) · main.py (router include).

Still gated on your decisions (unchanged): real Mandrill/SMTP transport +
public HTTPS webhook, real LinkedIn client, external LLM adapter.
