# Campaign operations phase — integration report

## 1. Final commit

**`5fea355`** on `main` (merge of `integrate/campaign-ops-2026-08-13`).
Preceding: `10e741c` (integration), `8bac4e7` (first merge).

## 2. Files changed (16)

**New:** `abm_platform/services/campaign_workspace.py`,
`abm_platform/services/campaign_dispatch.py`,
`alembic/versions/w0e2f4a6b8d0_campaign_workspace.py`,
`alembic/versions/x1f3a5b7c9d1_campaign_dispatch_runs.py`,
`tests/test_campaign_workspace.py`, `tests/test_campaign_dispatch.py`

**Modified:** `models_ext.py`, `abm_platform/services/jobs.py`,
`abm_platform/services/pipeline_jobs.py`, `abm_platform/services/marketing.py`,
`abm_platform/services/marketing_ext.py`, `routers/bd_parity.py`,
`routers/os_shell.py`, `deploy/worker_main.py`,
`tests/test_crm_marketing_ext.py`

Line endings first: the package is CRLF, this repo is LF. Stripped on the way
in, so the diffs above are real content differences rather than 100% noise.

**This package was genuinely rebased.** Unlike the previous three, it was built
on current code: the C-suite `db.flush()` gate, `campaign_preflight`, the
validated tracking base URL, the Email Analytics screen and the other dashboard
fixes all survive untouched. Verified before merging, not assumed.

## 3. Conflicts and decisions

### One conflict, and it was serious

`models_ext` declared `email_campaigns.brand_profile_id` as a
`ForeignKey("email_brand_profiles.id")`. But `email_campaigns` is created by the
**historical** migration `d4e8b1c5a7f9`, which builds every table in
`models_ext.ALL_TABLES` — and that runs long before `w0e2f4a6b8d0` creates
`email_brand_profiles`.

Result: `alembic upgrade head` **failed on a fresh database** with
`relation "email_brand_profiles" does not exist`, while passing on an
already-migrated one, because `checkfirst=True` skips the existing table. It
would have worked everywhere except a new deployment — including, presumably,
wherever it was tested.

**Fixed** by declaring the column without the FK and adding the constraint in
`w0e2f4a6b8d0` once both tables exist (`_ensure_brand_profile_fk`), so the
database still enforces referential integrity. Verified by building the entire
chain from an empty database.

### One behaviour change, reported rather than absorbed

`schedule_campaign()` now requires a **full live-delivery preflight** and
`approval_status == "approved"`. Previously it only checked "audience not
empty". This is correct — a campaign that cannot lawfully send should not be
schedulable — but it is a real tightening, and it broke `test_crm_marketing_ext`
whose fixture campaign had no unsubscribe link. The test now builds a compliant,
approved campaign; **the assertion it makes is unchanged.**

### One gap the package left

The dispatch API had progress and cancel endpoints; the dashboard called
neither. An operator could launch a batch run and then had no way to watch or
stop it — the panel showed a single line captured at page load. Now wired:
polls `/mkt/campaign-dispatch/` every 2s while active, shows all six counters,
surfaces `last_error`, and offers Cancel while the run is live.

### Requirement 8 — worker registration

`campaign_dispatch_batch` is registered inside `register_pipeline_handlers()`,
which `deploy/worker_main.py` calls — the only production worker entrypoint in
the repository (verified by grep, not assumption). Comment added there
explaining why every worker needs it: an unregistered kind fails, retries and
dead-letters, which presents as "the campaign stalled" rather than "this worker
is misconfigured".

## 4. Migration rehearsal

On a **clone** of the pre-migration schema, never the working database:

```
v9d1f3a5b7c9 (baseline)  →  w0e2f4a6b8d0  →  x1f3a5b7c9d1     UPGRADE    ok
  email_brand_profiles, email_campaign_revisions,
  campaign_dispatch_runs, campaign_dispatch_recipients        created
  fk_email_campaigns_brand_profile                            created

x1f3a5b7c9d1  →  w0e2f4a6b8d0  →  v9d1f3a5b7c9                DOWNGRADE  ok
  all four tables dropped                                     verified (0)
  brand-profile FK dropped                                    verified (0)

v9d1f3a5b7c9  →  x1f3a5b7c9d1                                 RE-UPGRADE ok
```

**Alembic heads: exactly one — `x1f3a5b7c9d1`.**

## 5. Test results by suite

Each in its own process with a distinct disposable database.

```
test_campaign_workspace          PASSED
test_campaign_dispatch      3    PASSED
test_jobs_async                  PASSED   (durable queue)
test_mailchimp_e2e               PASSED
test_email_lifecycle_e2e         PASSED
test_tracking_decision           PASSED
test_inbound               18    PASSED
test_crm2_api                    PASSED   (API)
test_os_shell                    PASSED   (dashboard smoke)
test_unified                     PASSED
test_crm_marketing_ext           PASSED   (after the scheduling-gate update)
full source compilation          PASSED
```

Dashboard operator flow against a live app on PostgreSQL — **5/5**: view
progress, all six counters exposed, `last_error` present for failed-run
visibility, cancel an active run, only `dry_run` registered.

## 6. Concurrent-worker and restart-recovery results

Two real worker **processes** against PostgreSQL — **16/16**:

- run created with a snapshotted audience (40)
- run reached a terminal state (`completed`)
- every snapshotted recipient has exactly one ledger row (40)
- **all recipients processed exactly once** (40)
- **no duplicate `EmailMessage` rows** — stable ids (40 unique)
- exactly one message per recipient
- dashboard progress matches the ledger (processed 40 = sent 40)
- **re-running the campaign created no duplicate messages** (40 → 40, sent=0)
- a job was left `running` by a **SIGKILL'd** worker (1)
- **expired worker lease recovered** (1)
- **campaign not stranded after the crash** — reached `completed`
- crash recovery produced no duplicate messages
- **cancelled run did not complete**; later batches did not run (0/40)
- only `dry_run` registered; every send request used `dry_run`

## 7. Live sending

**Disabled.** `delivery._TRANSPORTS` contains only `dry_run`. No Mandrill, SES,
Gmail, Microsoft 365 or SendGrid transport is registered. **SendGrid was not
configured, called or modified.** Dispatch runs are created with
`transport="dry_run"` and every send request in every test used it.

## 8. Unresolved production risks

1. **No live provider has ever been exercised.** Everything is dry-run.
2. **Lease recovery is time-based** (`stale_minutes=15`). A worker that is slow
   rather than dead can have its job reclaimed and run twice. The per-recipient
   ledger and stable message ids make that safe for *messages*, but a
   long-running batch could still be double-counted in run totals.
3. **`recover_stale()` runs inside `run_once()`**, so recovery only happens when
   some worker is alive. If every worker dies, nothing recovers until one
   returns — acceptable, but it means "no workers" and "stuck run" look alike.
4. **Cancellation is between batches, not within one.** A batch already claimed
   completes. That is the documented behaviour, but an operator cancelling a
   1000-recipient batch waits for it.
5. The webhook secret is still global (per-tenant secrets needed if tenants
   bring their own ESP account) and the analytics `.in_(msg_ids)` bind still
   needs a join before six-figure campaigns — both carried from the previous
   phase.

**Not production-live.** That still requires separate human approval plus
verified SPF, DKIM, DMARC, return path, HTTPS tracking domain, native webhook
configuration, PostgreSQL RLS behaviour, KSA send windows, mailbox warm-up,
complaint thresholds and a controlled seed-list delivery.

## Rollback

```
git revert -m 1 5fea355
python -m alembic downgrade v9d1f3a5b7c9
```
