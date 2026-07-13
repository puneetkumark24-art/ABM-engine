# Phase 1 — Drip Engine Hardening (Sequence Engine + Send Window)

Goal: turn the hardcoded "5 touches, one every 3 days, skip if replied" logic
into a real, data-driven sequencing engine (the "drip"), and close two active
gaps flagged by the project's own specs (Build Artifact 3, T-STATE-1 /
T-TIME-2) that were never actually implemented in code. Nothing here touches
the Bible's 12-stage / 1,065-rule build plan (Postgres schema, Rule_Registry,
EPIS, Autonomy Ladder, etc.) — that is a separate, much larger effort. This is
scoped tightly to the outreach cadence itself, additive, and backward
compatible: a machine that hasn't pulled these files still runs exactly as
before.

## What was actually wrong (found by reading the live code, not assumed)

1. **`get_contacts_due_for_outreach` never checked `do_not_contact` or
   `consent_status`.** Both columns exist on the live `contacts` table (added
   by an earlier migration) but nothing in the query filtered on them — a
   contact marked do-not-contact or explicitly denied consent could still get
   a fresh draft generated. This is the same class of bug the project's own
   bug history calls out ("Consent system was decorative — never enforced")
   — it had regressed.
2. **`get_approved_unsent_drafts` never re-checked `replied` / `do_not_contact`
   at send time.** A draft approved before a reply came in would still send
   after the reply, because the send job only checked `status='APPROVED'`.
   This is exactly Build Artifact 3's **T-STATE-1** ("reply mid-sequence
   pauses; next scheduled touch does not send") — untested and, on
   inspection, not actually true of the code.
3. **No KSA send-window enforcement anywhere** (`grep -rn
   "friday|blackout|ramadan"` across the whole package returned zero hits
   before this change). Build Artifact 3 names this explicitly as
   **T-TIME-2** ("Send attempt Friday or during Ramadan blackout returns
   403"). The scheduler would happily fire `send_approved_drafts` at 2am or
   on a Friday.
4. **Cadence was a hardcoded constant** (`current_touch < 5`, `-3 days`)
   instead of data, so "connectors get a slower cadence" or "HOT accounts get
   touch 2 sooner" was impossible without another if/elif branch per case.

## What was built

### `abm_engine/workflow/` (new package)

- **`send_window.py`** — `is_within_send_window(now=None) -> (bool, reason)`.
  Blocks the KSA weekend (Fri/Sat by default), outside-business-hours sends,
  and any date listed in an optional JSON blackout-dates file
  (`RAMADAN_BLACKOUT_DATES_FILE` env var — empty/unset by default, since Hijri
  holiday dates shift every Gregorian year and shouldn't require a code
  change). All thresholds are env-configurable
  (`SEND_BLACKOUT_WEEKDAYS`, `SEND_WINDOW_START_HOUR`, `SEND_WINDOW_END_HOUR`).

- **`sequence_db.py`** — three new additive tables:
  `sequence_definitions` (named cadence, optionally scoped to a
  `relationship_type`), `sequence_steps` (per-step channel +
  `wait_days_after_previous`), `sequence_enrollments` (one row per
  contact×sequence, with `status` ACTIVE/PAUSED/COMPLETED/EXITED and
  `current_step`). Nothing here replaces `contacts`, `draft_messages`, or
  `touch_records` — it sits alongside them.

- **`sequence_engine.py`** — the policy layer:
  - `ensure_default_sequence()` — idempotent; recreates today's implicit
    cadence (5 steps, EMAIL+LINKEDIN together, 3-day gaps) as an explicit,
    editable row set. Editing the cadence going forward is a data change
    (`UPDATE sequence_steps ...`), not a code change.
  - `backfill_enrollments()` — idempotent; enrolls every active contact that
    isn't enrolled yet, **starting at their existing `current_touch`**, so no
    contact's progress resets when this ships.
  - `get_contacts_due(limit)` — same compliance gates as the old query
    (`is_active`, `replied=0`, `do_not_contact=0`, `consent_status!='denied'`),
    but "due" is computed from each contact's actual sequence step instead of
    a hardcoded constant.
  - `advance(contact_id)` / `pause(contact_id, reason)` — called after a send
    succeeds / on reply.

### Wiring (`core/orchestrator.py`, `channels/webhook_server.py`)

- `generate_drafts()` now calls `sequence_engine.get_contacts_due()` first,
  and **falls back to the original `db.get_contacts_due_for_outreach()`** if
  the sequence engine raises for any reason (e.g. a machine that hasn't run
  the new code yet) — outreach never silently stops because of this change.
- `send_approved_drafts()` now checks `is_within_send_window()` first. Outside
  the window, it returns `{"sent": 0, "skipped_window": reason}` and sends
  nothing; approved drafts stay approved and unsent, they are never dropped.
- `_send_draft()` now calls `sequence_engine.advance(contact_id)` in addition
  to the existing `db.increment_touch(contact_id)` (kept for the dashboard,
  which still reads `current_touch` directly).
- `webhook_server.py`'s inbound-reply handler now calls
  `sequence_engine.pause(contact_id, "replied")` right after the existing
  `mark_contact_replied(contact_id)`.

### `db.py` (two surgical query changes, everything else untouched)

- `get_contacts_due_for_outreach`: added
  `AND COALESCE(do_not_contact,0)=0 AND COALESCE(consent_status,'')!='denied'`.
- `get_approved_unsent_drafts`: added
  `AND c.replied=0 AND COALESCE(c.do_not_contact,0)=0 AND COALESCE(c.consent_status,'')!='denied'`.

## Verification performed

`test_sequence_engine.py` (repo root, run with `python test_sequence_engine.py`
from `decimal_abm/`) — **operates only on a temp copy of `abm_engine.db`,
never the live file.** 13/13 checks pass:

- Default sequence creates correctly (5 steps, 3-day cadence, step 5 final).
- Backfill enrolls every active contact exactly once (idempotent on rerun).
- Setting `do_not_contact=1` removes a contact from `get_contacts_due`
  immediately.
- A contact touched "today" is not due again same-day; the same contact
  becomes due once `wait_days_after_previous` has elapsed.
- `advance()` increments `current_step` through 4 steps, then the 5th
  (final) advance sets `status=COMPLETED`.
- `pause()` sets `status=PAUSED` with the reason recorded.
- `is_within_send_window()`: Friday noon blocked, Sunday 10am allowed, Sunday
  11pm (outside business hours) blocked.

Also verified: `python -m py_compile` on every changed/new file, and a live
`import` of `abm_engine.core.orchestrator` and `abm_engine.channels.webhook_server`
in this environment (both import cleanly with the project's actual
dependencies installed).

**Not yet verified live**: an actual end-to-end scheduler run against the
real `abm_engine.db` (the scheduler wasn't started as part of this change —
only tested against a disposable copy, per the "no sending yet" project
constraint). Recommend running `python -m abm_engine status` after pulling
this, then one manual `python -m abm_engine run` cycle, before trusting the
cron schedule.

## What this deliberately does NOT do

- Does not touch the Postgres migration (`migrate_sqlite_to_pg.py`) — that's
  a separate, already-started effort.
- Does not implement the Bible's Rule_Registry, EPIS spine, Autonomy Ladder,
  dual-score opportunities, or any Stage 8+ concept from Build Artifact 3.
  Those are a different scale of project; this PR is scoped to "the drip"
  specifically, per what was actually asked.
- Does not add a UI for editing sequences/steps — they're editable via SQL
  today (`sequence_definitions` / `sequence_steps`). A dashboard tab for this
  is a natural next step if the team wants non-technical cadence editing.
- Does not wire `add_unsubscribe()` / `update_contact_consent()` in
  `dashboard/app.py` to call `sequence_engine.pause()` directly — left out to
  avoid touching the dashboard in this pass. Not a compliance gap: both
  `get_contacts_due()` and `get_approved_unsent_drafts()` re-check
  `do_not_contact`/`consent_status` on every call, not just at enrollment
  time, so this is a nice-to-have (cleaner enrollment-status reporting), not
  a safety fix.

## Env vars added (all optional, all have working defaults)

| Var | Default | Purpose |
|---|---|---|
| `SEND_BLACKOUT_WEEKDAYS` | `4,5` (Fri, Sat) | Python `weekday()` values to block sends on |
| `SEND_WINDOW_START_HOUR` | `8` | Local (Asia/Riyadh) hour sends may start |
| `SEND_WINDOW_END_HOUR` | `18` | Local hour sends must stop |
| `RAMADAN_BLACKOUT_DATES_FILE` | unset (no-op) | Path to a JSON array of `"YYYY-MM-DD"` blackout dates |
