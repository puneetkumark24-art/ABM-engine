# Integration Report — Candidate v4 (unified ABM + marketing + CRM), 2026-08-02

> **STATUS: MERGED.** Merge commit `188ab35` on `main`, a `--no-ff` merge of
> `integrate/v4-unified-2026-08-02` (head `e6fe1f6`) onto the v2 merge `ca4981e`.
> Merged on the merge-if-green basis approved in advance. Real outreach was
> **not** enabled and remains `dry_run`-only, re-verified after the merge.

## The headline finding

The candidate's fix for overlapping engine ticks (audit item 10, described there
as "safe across internal commits") **is not safe, and its failure mode is a
silent engine outage.** This was not taken on trust in either direction — it was
measured.

It holds a PostgreSQL *session* advisory lock on the SQLAlchemy `Session`. A
session advisory lock belongs to the specific backend connection that took it. A
`Session` returns its connection to the pool on `commit()`, and an engine tick
commits internally more than once. Against a disposable PostgreSQL, under two
concurrent ticks:

```
thread1: WON. locked on pid=21, unlocked on pid=21, same_backend=True,  unlock_returned=True
thread0: WON. locked on pid=24, unlocked on pid=21, same_backend=False, unlock_returned=False
locks remaining on key after both threads finished and closed: 1
```

The Session came back on a **different backend in 3 of 4 runs**, so
`pg_advisory_unlock` ran on the wrong connection, returned false, and the lock
was never released. A follow-up probe in a single long-lived process (as a real
API or scheduler is) showed the consequence directly:

```
racing tick 0: SKIPPED -- 'another engine tick is already running'
racing tick 1: ran
stranded locks after the race: 1
now the scheduler keeps firing, same process, same pool:
  later tick 1: SKIPPED -- 'another engine tick is already running'
  later tick 2: ran
  ...
```

Stranded locks accumulate on idle pooled connections. Once every connection in
the pool holds one, **every** tick skips and the engine stops dispatching
permanently — while printing output indistinguishable from a normal idle engine.
Nothing alerts. A single-threaded test would never catch it: in the
non-concurrent probe the connection stayed put and all checks passed.

**What shipped instead:** the lock is held on a dedicated connection pinned for
the tick's duration and never returned to the pool mid-tick. It is also
self-healing — if the process dies, the connection closes and PostgreSQL drops
the lock automatically, unlike a stranded pooled connection which needs manual
unjamming. The existing row-level `FOR UPDATE SKIP LOCKED` on approved drafts
(proven in an earlier session) is **kept alongside it**, not replaced as the
candidate does. `tests/test_tick_lock.py` pins the exact property that failed —
*no lock stranded after concurrent ticks* — so the Session-based version cannot
return unnoticed.

## What was integrated

- **Growth Operations** — one read model and dashboard across monitored accounts
  → fresh signals → contactable people → active nurture → engaged → open
  pipeline, with approval, task and delivery-failure queues. Contactable counts
  correctly exclude suppression-list and denied/withdrawn-consent records.
- **Journeys actually execute** — send nodes deliver through the shared dry-run
  engine with deterministic per-enrollment message ids, merge rendering,
  attribution and account rescore. Enrollment validates contactability and is
  idempotent. Branch conditions read real open/click events; previously they were
  hard-coded to `False`, so every branch was structurally dead.
- **Campaign safety** — exactly-once per campaign/contact, and a **c-suite
  recipient now creates a real approval draft instead of being counted as sent**.
  The campaign stays `awaiting_approval` until every executive draft is released.
- **Inbound feedback loop** — delivery events update engagement and account
  scoring immediately; hard bounce, complaint, spam and unsubscribe enforce
  do-not-contact, with complaint and unsubscribe also recording denied consent.
- **Dashboard** — command dashboard, Signal Command Center (with a new read-only
  `/signal-review/coverage` endpoint), mobile nav, responsive grids,
  overflow-safe tables, keyboard focus, skip-to-content, auth failures routing to
  sign-in rather than reading as "service uninitialized".
- **Data hygiene** — audience preview is read-only and no longer leaves a
  throwaway audience row behind on every click.

16 files changed, 759 insertions, 48 deletions. **No schema change; no new
Alembic migration.**

## What was rejected, and why

Ten files would have reverted work already verified on `main`: the signal export
quality gates, the Alembic partition-child downgrade fix, the RLS suite's
self-healing DDL and captured-`DATABASE_URL` fix (which had caused a **false
pass** on the most important check in that file), the `test_tenant_writes`
order-independence fix, the pytest wrappers on six script-style suites, and the
completeness of `test_engine_e2e`'s model imports. `config.py`,
`routers/pipeline_ops.py` and both `.bat` files differed only in comment wording.
Per-file rationale with evidence is in `INTEGRATION_MAP_v4_2026-08-02.md`.

## Two more defects the test gate caught

Both **pre-existing** — reproduced on `main` before changing anything — but both
would have left the merge red, so both were fixed:

1. **Four suites failed against a migrated PostgreSQL.**
   `test_sales_engagement`, `test_tracking_decision`, `test_sprint1_platform`
   and `test_security_compliance` all died with
   `DependentObjectsStillExist: cannot drop table opportunities` — `drop_all()`
   only knew about the model modules each file happened to import, so it tried to
   drop `opportunities` while `quotes.opportunity_id` still referenced it.
   `tests/conftest.py` now imports every model module, fixing all of them at once
   (pytest loads conftest before any test module, and SQLAlchemy's registry is
   process-global). Imports-only, so it cannot mask a real defect.

2. **A genuine regression from the new behaviour, caught and resolved properly.**
   `test_platform_services` asserts exact attribution credit splits over exactly
   three touches — and campaign sends now correctly record attribution touches on
   the same fixture account, adding three more. The fix isolates those checks to
   a dedicated account **and** adds a direct assertion that a campaign send
   records attribution touches, so the new behaviour is tested rather than merely
   worked around.

## Tests — exact results

Every run against a real disposable PostgreSQL 16 (`pgserver`), migrated with
`alembic upgrade head`. Never SQLite-only, never a production database.

**New / directly affected:**

```
tests/test_tick_lock.py            9/9 checks   PASSED   (3 concurrent races, zero stranded locks)
tests/test_unified.py                           PASSED
tests/test_journeys.py                          PASSED
tests/test_crm_marketing_ext.py                 PASSED
tests/test_engine_e2e.py                        PASSED
tests/test_platform_services.py                 PASSED
tests/test_concurrent_dispatch.py               PASSED
tests/test_os_shell.py                          PASSED
```

**Full sweep — all 43 collected test files verified PASSED**, including the four
previously-red ones and `test_alembic_roundtrip`, `test_tenancy_rls` (with the
RLS half genuinely active, not guard-skipped), `test_real_partitioning`,
`test_scale_db`, `test_scale_hotpaths`, `test_perf_harness`, `test_crm2`,
`test_crm2_api`, `test_inbound`, `test_operator_console`, `test_master_data`,
`test_workflow_durable`, `test_developer_platform`, `test_final_wave`,
`test_jobs_async`, `test_parity_mission`, `test_scoring`, `test_signal_v2_bridge`,
`test_sequence_engine`, `test_cohorts`, `test_cache_ratelimit`,
`test_autonomous_loop`, `test_abm_intel`, `test_ai_orchestrator`, and
`test_sprint1`–`test_sprint6`.

**Contamination check** — five suites in one process in collection order
(`test_engine_e2e`, `test_platform_services`, `test_sales_engagement`,
`test_tenancy_rls`, `test_tenant_writes`): **5 passed**. Multiple other 2–4 file
combinations also passed in-process.

**Honest limit:** this sandbox caps every shell call at 45 seconds and the
complete `pytest tests/` run exceeds that, so a single end-to-end whole-suite
invocation was **not** completed here. What was verified is exactly what is
listed above: every file individually on a freshly migrated database, plus
several in-process combinations. Worth running once on your machine.

## Security review

- **No real credentials** anywhere in the candidate zip; two `.env.example` files
  hold placeholders only. Nothing in this candidate requires rotation. (Unrelated
  to any credential that may exist in older git history — that remains a separate
  standing item.)
- **No `.env`, database, dump, log, cache or test artifact** imported.
- **Dry-run enforcement**, re-verified after the merge: all five `transport=`
  call sites in the changed services pass `"dry_run"` literally;
  `send_campaign` defaults to `dry_run` and all four of its callers pass it
  explicitly; only the dry-run transport is registered at import; the SES,
  Mandrill, Gmail and Microsoft 365 adapters stay inert behind opt-in env flags
  that are not set, and nothing calls their `try_register_*()` at startup.
- **The new consent logic is restrictive-only** — bounce, complaint, spam and
  unsubscribe can set `do_not_contact` and denied consent, never clear them.
- **Audit trail** covers every table the new logic mutates: `drafts` (campaign
  approvals), `email_campaigns` (status transitions) and `persons`
  (do-not-contact / consent changes) are all in `AUDITED_TABLES`, so approvals,
  rejections, sequence transitions and consent changes are captured with
  before/after values. `email_messages` and `journey_enrollments` are not —
  pre-existing, and worth a look, but no consent- or approval-bearing state
  lives only there.

## Outstanding — unchanged by this merge

Everything in the audit's own release-blocker list still stands: signal coverage
at 35.61% against a 90% target, the human quality-calibration sample, live
PostgreSQL/RLS acceptance against a production clone, Redis-backed throttling and
SSO/MFA, provider sandbox and kill-switch drills before any real delivery, and
full browser / keyboard / RTL / accessibility QA. The correct label remains
**hardened local production candidate, shadow/dry-run only**.

Two items to add:

- The candidate's tick-lock defect (above) is worth reporting back to whoever
  produced it — the same pattern may exist elsewhere in that codebase.
- There is still no GitHub remote in this environment, so there is no PR link.
  History is delivered as a git bundle: `git clone drip_v4_merged.bundle repo`
  gives you real branches you can push wherever you host.

## Rollback

```
git revert -m 1 188ab35
```

`-m 1` keeps the pre-v4 parent. No migration ran and no data changed, so the
revert is complete on its own.
