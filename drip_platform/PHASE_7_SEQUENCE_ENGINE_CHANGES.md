# Phase 7 — Sequence / Journey Engine (Enterprise Blueprint Module 08)

**What this is:** the "Outreach Execution port" named in `MASTER_CONSOLIDATION_PLAN.md`
§5 as *"the core of subsuming the drip."* It ports decimal_abm's proven Phase 1
sequencing (5-touch cadence, KSA send-window, compliance gates) onto DRIP's ORM
`Person`/`Organization` model, so the outreach cadence lives in the single engine
(`drip_platform/`) instead of only in decimal_abm's SQLite.

It also lands the first native piece of the enterprise redesign inside the real
codebase — Module 08 (Journey Engine) from `ABM_Enterprise_Platform`.

## Guarantees honoured (from the consolidation plan)

- **Additive only.** Four new tables, one new package, one new router, one Alembic
  migration. **No existing column changed** — same discipline as the SIG-TENDER /
  SIG-PARTNER and EPIS-decay additions.
- **decimal_abm untouched.** Its live outreach keeps running; this does not flip any
  scheduler over. The port is proven here first; cut-over is a later, separate step.
- **Test gate before proceeding.** `tests/test_sequence_engine.py` — **30/30 checks
  pass** against SQLite (in-memory), mirroring `test_signal_decay.py`'s style.

## Files added

| File | Purpose |
|---|---|
| `models.py` (appended) | `SequenceDefinition`, `SequenceStep`, `SequenceEnrollment`, `SequenceEnrollmentEvent` — four additive ORM tables. |
| `sequences/__init__.py` | package doc. |
| `sequences/send_window.py` | KSA business-hours + Fri/Sat + Ramadan-blackout gate (T-TIME-2). Ported from decimal_abm; only change is stdlib `logging` instead of `loguru` (not a DRIP dep). |
| `sequences/engine.py` | ORM policy layer: `ensure_default_sequence`, `enroll_person`, `backfill_enrollments`, `get_due`, `advance`, `pause`, `resume`, `pause_on_reply`. |
| `routers/sequences.py` | FastAPI surface; every write goes through the engine so compliance is never bypassed. |
| `alembic/versions/c7d1f0a2b9e4_add_sequence_engine_tables.py` | additive migration, `down_revision = b1e4a9c07d32` (current head). |
| `tests/test_sequence_engine.py` | 30 checks. |
| `main.py` (edited) | `include_router(sequences.router)`. |

## Behaviour

- **Default cadence** reproduced exactly: 5 touches, email+linkedin ("both"), 3-day
  gaps, step 5 final — as editable data (`SequenceDefinition`/`SequenceStep`), not a
  hardcoded constant.
- **Compliance gate** (`is_contactable`) blocks enrolment/sending for
  `is_active=False`, `do_not_contact`, `consent_status='denied'`, or `replied=True`
  — read off DRIP's `Person` columns, identical in spirit to decimal_abm.
- **Due computation is portable** — done in Python (`next_run_at <= now`) rather than
  dialect-specific `datetime()` SQL, fixing the one place the raw-SQL original was
  SQLite-locked. Runs unchanged on Postgres.
- **Send-window gate**: `get_due(respect_send_window=True)` returns `[]` when the KSA
  window is closed (a skip, not an error), so due contacts simply go out on the next
  in-window tick.
- **ACC-001 account-centric pause**: `pause_on_reply(person_id)` pauses the replier's
  enrollments **and every other ACTIVE enrollment at the same organization**, and sets
  `person.replied=True`. Verified: replying at Al Rajhi pauses all Al Rajhi enrollments,
  SNB untouched.

## How to apply on your machine (Postgres)

```bash
cd drip_platform
alembic upgrade head            # runs b1e4a9c07d32 -> c7d1f0a2b9e4 (4 new tables)
python tests/test_sequence_engine.py   # expect 30/30
uvicorn main:app --reload       # new endpoints under /sequences in /docs
# one-time: seed the default cadence + enrol existing contactable people
curl -X POST localhost:8000/sequences/ensure-default
curl -X POST localhost:8000/sequences/backfill
```

## API surface (new)

```
GET  /sequences                       list sequences (+ steps)
POST /sequences/ensure-default        create/repair the default 5-touch cadence
POST /sequences/enroll                {person_id, sequence_id?}  (409 if compliance-blocked)
POST /sequences/backfill              enrol all eligible active persons
GET  /sequences/due?limit&respect_send_window   contacts due to be touched now
POST /sequences/enrollments/{id}/advance        after a successful send
POST /sequences/enrollments/{id}/pause          {reason}
POST /sequences/enrollments/{id}/resume
POST /sequences/reply                 {person_id, reason}  -> ACC-001 account pause
GET  /sequences/enrollments/{id}/events         audit trail
```

## Not done yet (next increments, per the plan)

1. **Wire drafting + actual send** into `advance()` — generate the step's `Draft`
   (Gemini) and dispatch via the delivery layer, then call `advance`. Today `advance`
   moves the state machine; it does not itself send (deliberate — no live sending until
   you enable it).
2. **Mailchimp-replica `email_events`** (Module 11/07) — Mandrill send + webhook capture
   feeding engagement back into `AccountScore` reachability. Needs the public-HTTPS
   webhook decision (VPS vs ngrok).
3. **Scheduler tick** calling `get_due` -> draft -> send -> `advance` on a cron.
4. **Relationship-typed sequences** — populate `SequenceDefinition.relationship_type`
   per `OrgTypeTag` so vendors/connectors/decision-makers get distinct cadences.
