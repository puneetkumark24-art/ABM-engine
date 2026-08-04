# Integration Report — Candidate v2 (2026-08-02)

> **STATUS: MERGED.** Approved and merged on 2026-08-02 after review.
> Merge commit `ca4981e` on `main`, a `--no-ff` merge of
> `integrate/v2-candidate-2026-08-02` (branch head `0178d3f`) onto baseline
> `e40f461`. Outbound delivery was **not** enabled and remains `dry_run`-only —
> re-verified post-merge (§9). One additional fix was made during the pre-merge
> gate; see §9.



Systematic integration of `DRIP_CTO_dashboard_hardened_candidate_v2_2026-08-02.zip`
into the real DRIP repository, per the audit-first / map-first / branch-based process
requested. Stopped before merge, as instructed — everything below is on a branch,
nothing is on `main`, nothing was pushed anywhere, and outbound delivery is untouched
(`dry_run` only throughout).

## Environment limitation, stated upfront

This sandbox could not run git directly inside your synced Desktop folder
(`C:\Users\Puneet\Desktop\ABM business logic\drip_platform`) — the Windows-mount
bridge rejects `unlink` on git's lock files after any interrupted operation, so
`git add`/`git commit` there gets permanently stuck. Confirmed by trying multiple
removal strategies (`rm`, Python `os.remove`, `mv` all failed or only partially
worked). **A harmless, empty, non-functional `.git/` folder was left behind in that
directory as a result** — it has no commits and isn't usable; delete it from Windows
Explorer directly (that side doesn't hit the same restriction) whenever convenient.

Workaround: did the actual branch/commit/test workflow in an isolated Linux-native
working copy, then copied only the final, tested files back into your real folder —
the same verification method used all session. You get:
- A **git bundle** (`drip_git_v2_integration.bundle`) — a full, self-contained git
  history with both `main` (baseline) and `integrate/v2-candidate-2026-08-02`
  branches. On any machine with git: `git clone drip_git_v2_integration.bundle drip_repo`
  gives you real branches and commit history you can push to GitHub/wherever you host.
- A **plain diff** (`drip_v2_integration.patch`) of everything the branch changed,
  if you'd rather review or apply it by hand.
- No commit hash to quote as authoritative and no PR link — there's no GitHub
  remote connected in this environment. Branch head commit in the bundle:
  `d544b60` ("Integrate v2 candidate: method-aware CRM authz, duplicate-held-draft
  prevention, approval rescore, dashboard error feedback"), on top of baseline
  `e40f461`.

## 1. Audit → integration map

Full audit read (`CTO_DASHBOARD_AUDIT_v2_2026-08-02.md`) and complete file-by-file
diff against the real repo as it stands today (not an old snapshot) — see
`INTEGRATION_MAP_v2_2026-08-02.md` for the full table. Headline finding: 22 files
differed; **5 were genuinely new and correct, 5 were the candidate reverting fixes
already verified working earlier today, and the rest were cosmetic or already
identical.** Nothing was chosen silently — every reject below is because taking the
candidate's version would have reintroduced a bug already found, reproduced, and
fixed with evidence this session.

## 2. Files changed (integrated)

| File | Change |
|---|---|
| `tenant_middleware.py` | Method-aware authorization: GET requires `crm.read`, POST/PUT/PATCH/DELETE require `crm.write`. Added explicit scope coverage for `/organizations`, `/persons`, `/signals`, `/opportunities`, `/sales`, `/signal-review`, `/dev`, `/compliance`, `/workflow` — previously uncovered, meaning any authenticated principal (any scope at all) could hit them. Fixed a route-boundary bug: `path.startswith(prefix)` matched `/crmevil` against `/crm`. |
| `abm_platform/services/orchestrator.py` | (1) A c-suite enrollment stays "due" while its draft awaits human review — every tick was generating another duplicate pending draft for the same person/step; now skipped once one exists (`existing_drafts_skipped` in the tick report). (2) Human-approved dispatches now feed into the same engagement-rollup/rescore loop as automatic sends (previously only automatic sends rescored the account). Kept the existing, already-proven `FOR UPDATE SKIP LOCKED` row-level concurrency protection as-is. |
| `routers/os_shell.py` | Approve/Pause/Resume buttons now surface backend failures (e.g. a 409 from an invalid state transition) instead of silently refreshing as if the action succeeded. Approve also clarifies dispatch happens on the next engine cycle, not immediately. |
| `tests/test_tenant_writes.py` | New assertions for the authorization changes (route-boundary, read-vs-write scope, admin-only surfaces). |
| `tests/test_engine_e2e.py` | New assertion: a repeated tick before human review does not duplicate the held draft. Kept the existing import-completeness fix from earlier today (unrelated but in the same file). |

**Not changed, deliberately:** every PostgreSQL model, every existing Alembic
migration's logic, the HubSpot integration, every other route, authentication
mechanics beyond the scope-check above, tenant isolation/RLS, and current UI
behavior outside the three button handlers listed. No schema change anywhere in
this integration — **no new Alembic migration required.**

## 3. Rejected from the candidate (regressions, not silently dropped)

| File | Why rejected |
|---|---|
| `abm_platform/services/signal_v2_bridge.py` | Candidate strips the quality-gate hardening merged earlier today (drops `action_eligible=0`, `quality_decision='pass'`, completeness/materiality thresholds, pending-contradiction check) — reverts to trusting `scoring_eligible=1` alone. That hardening was verified against real captured signal data. |
| `alembic/versions/d1a2b3c4e5f6_add_tenancy_and_rls.py` | Candidate's `downgrade()` is the version that breaks on partition child tables — proven broken today via a real upgrade→downgrade→upgrade round trip (`InvalidTableDefinition: cannot drop inherited column`). Current version fixes this and passes the round trip twice. |
| `.github/workflows/ci.yml` | Candidate lacks `DRIP_ALLOW_PG_TESTS: "1"`, added today so CI's disposable Postgres actually runs the RLS-isolation proof instead of silently skipping it. |
| `tests/test_tenancy_rls.py` | Candidate reverts two proven fixes: idempotent schema re-assertion (without it, another test's `drop_all()` silently wipes the RLS columns) and reading `DATABASE_URL` from a value captured once at session start rather than live (without it, another test's env mutation caused this suite's RLS checks to silently report "skipped" while still going green — a false pass on the most important check in the file). |
| `tests/test_signal_v2_bridge.py` | Candidate reverts a before/after table-existence comparison to an unconditional assertion that fails against an already-migrated shared Postgres — reproduced today as a real false failure. |
| 6 script-style test files (`test_ai_orchestrator.py`, `test_sprint2` through `test_sprint6`) | Candidate lacks the pytest wrappers added today; without them CI's `pytest -q tests/` silently runs 0 of their ~120 checks. The candidate's own audit report lists this as an *unresolved* blocker in their copy — consistent with what's found here. |

One item from the candidate was evaluated and **intentionally not adopted as-is**:
a whole-tick PostgreSQL session-advisory-lock wrapper (`pg_try_advisory_lock`/
`pg_advisory_unlock`, with a `threading.Lock` fallback on SQLite). The concept is
sound, but session-scoped advisory locks are tied to whichever DBAPI connection
SQLAlchemy's `Session` currently holds — `_dispatch_human_approved` and `run_tick`
both commit internally, and a `Session` isn't guaranteed to keep the same pooled
connection across a commit under real concurrent load. If it doesn't, the unlock at
the end could silently fail to release the *actual* lock, permanently jamming every
future tick that happens to check out that connection — a worse failure mode than no
lock at all. This needs its own concurrency proof (real threads, real Postgres,
multiple internal commits) before being trusted, the same bar the existing row-level
lock was already held to and passed. Flagged as follow-up work, not silently dropped.

## 4. Tests executed — exact results

All against a real, disposable PostgreSQL 16 (`pgserver`), migrated via
`alembic upgrade head` first, never SQLite-only and never a real/production database.

**Focused suite (the specific list requested), all PASSED:**
```
tests/test_engine_e2e.py::test_engine_e2e                                  PASSED
tests/test_tenant_writes.py::test_tenant_writes                            PASSED
tests/test_tenancy_rls.py::test_tenancy_rls                                PASSED
tests/test_concurrent_dispatch.py::test_concurrent_dispatch                PASSED
tests/test_signal_v2_bridge.py::test_account_map_excludes_decimal...       PASSED
tests/test_signal_v2_bridge.py::test_export_is_one_way_and_idempotent...   PASSED
tests/test_signal_v2_bridge.py::test_unmapped_account_is_skipped...        PASSED
tests/test_alembic_roundtrip.py::test_alembic_roundtrip                    PASSED
tests/test_os_shell.py::test_os_shell                                      PASSED
tests/test_sequence_engine.py::test_sequence_engine                        PASSED
tests/test_sprint1_platform.py::test_sprint1_platform (AUTH_ENFORCED=true) PASSED
```
That covers: concurrent engine ticks (`test_concurrent_dispatch` — proved with real
racing threads), duplicate held-draft prevention (`test_engine_e2e`'s new assertion),
approval-to-dispatch lifecycle (`test_engine_e2e`), exactly-once sequence advancement
(`test_engine_e2e`, `test_concurrent_dispatch`), CRM read/write authorization and
route boundaries (`test_tenant_writes`), tenant isolation/RLS (`test_tenancy_rls`,
run with the RLS half genuinely active, not guard-skipped), signal quality/
completeness/attribution gates (`test_signal_v2_bridge`), HMAC signature and replay
rejection (covered by `test_tenancy_rls`'s webhook half; the capture-webhook HMAC
itself was proven live via `TestClient` in the previous integration round), dashboard
control bindings (`test_os_shell`), outbound dry-run enforcement (verified directly
below, §5).

**Broader regression pass, all PASSED individually/in small groups:**
`test_security_compliance`, `test_operator_console`, `test_unified`, `test_crm2`,
`test_crm2_api`, `test_sales_engagement`. (Running all six together in one process
hit a pre-existing, already-documented fragility — some script-style test files
share one live database across the whole pytest session and don't all import the
same complete model set, which is a known issue flagged in today's earlier
production-readiness report, not something this integration introduced. Every file
individually confirmed clean.)

**Whole-suite sanity:** `pytest --collect-only tests/` collects 63 tests with no
crash; `python -m compileall` on the full repo is clean.

## 5. Security review

- **Credential scan:** no AWS keys, API tokens, private key blocks, or embedded
  DB-URI credentials found anywhere in the candidate zip (regex-scanned across
  `.py`, `.md`, `.env*`, `.yml`, `.json`). One placeholder string found
  (`JWT_SECRET: "REPLACE_WITH_VAULT_SECRET"` in a k8s manifest) — not a real secret.
  **Nothing in this candidate requires credential rotation.** (This doesn't cover
  anything outside today's zip — if a real `.env` or credential was ever committed
  to git history at any point, that's a separate, standing action item regardless of
  this integration.)
- **No `.env`, database, dump, log, cache, or test-artifact files** were present in
  the candidate zip or imported. Two directories in the zip (`_signal_v2_backups/`,
  `_tmp_orig_bridge_test/`) are copies of this session's own earlier scratch/backup
  folders, not candidate content — excluded from integration.
- **Outbound dry-run enforcement:** confirmed both call sites in `orchestrator.py`
  still pass `transport="dry_run"` explicitly; `delivery.py` (untouched) only
  registers the `dry_run` transport by default. No SendGrid/Mandrill/SES code path
  is wired in or activated anywhere in this change.
- **Authorization change is strictly additive/more restrictive**, never more
  permissive: every new scope requirement narrows access; the route-boundary fix
  closes a real gap (`/crmevil` bypassing `/crm`'s scope check); confirmed no
  existing passing test regressed under `AUTH_ENFORCED=true`.
- **Audit trail:** `drafts` and `sequence_enrollments` — the two tables this
  integration's new logic touches — were already in `audit_trail.py`'s
  `AUDITED_TABLES`, unchanged by this work, so every approval, rejection, and
  sequence transition through the new code is already captured with before/after
  values. (`account_scores`, written by the rescore loop, is not in that list —
  pre-existing, since automatic sends already exercised the same rescore path
  before this change; not a new gap, but worth a future look.)

## 6. Unresolved blockers (carried forward, not solved by this integration)

Everything already listed in `PRODUCTION_READINESS_2026-08-02.md` still applies
(human signal-review calibration, HubSpot backfill/LinkedIn access, credential
rotation process, production Redis, browser/accessibility QA, import-completeness
audit across the rest of the test suite). Plus, from this round specifically:
- The candidate's whole-tick advisory lock needs its own concurrency proof before
  being trusted (§3) — not merged.
- No GitHub remote connected in this environment — branch exists only as a local
  git history (bundle) plus a plain patch file; pushing/opening a PR is a step you'll
  need to do from a machine with real GitHub access.

## 7. Rollback

Nothing was merged to `main`/production. To discard entirely: delete the 5 modified
files' current content and nothing else needs undoing (no migration ran, no data
changed, no service restarted with new code). If you clone the bundle and later want
to back out after merging, `git revert d544b60` on top of it cleanly reverts every
file this integration touched, since it's a single, self-contained commit.

## 8. Files delivered

- `INTEGRATION_MAP_v2_2026-08-02.md` — full file-by-file map (produced before any code change, per your process).
- `INTEGRATION_REPORT_v2_2026-08-02.md` — this report.
- `drip_v2_merged.bundle` — real git history including the merge commit, clone-able.
- `drip_v2_merged.patch` — plain diff `e40f461..main` (everything the merge brings in).

*(The earlier pre-merge `drip_git_v2_integration.bundle` / `.patch` are superseded
by the two above but left in place if you want the un-merged state.)*

---

## 9. Post-approval: pre-merge gate, one extra fix, and the merge

### A real bug found at the merge gate — and fixed

Re-running the tests immediately before merging surfaced a failure that the
earlier per-file runs had missed, because it only appears when files run
**together in collection order**:

```
tests/test_tenant_writes.py::test_tenant_writes FAILED
  psycopg2.errors.UndefinedColumn: column "tenant_id" does not exist
```

`test_engine_e2e.py` (and several other script-style suites) call
`Base.metadata.drop_all()` + `create_all()`. That drops and recreates
`organizations` — an ORM-mapped table — but knows nothing about `tenant_id`, its
GUC-reading default, or the RLS policy, because those exist **only** as raw SQL
inside migrations `d1a2b3c4e5f6` and `g4d6e8f0a2b3`, never as ORM columns. The
tenancy DDL was silently erased before `test_tenant_writes.py` ran — and since
alphabetical collection order puts `test_engine_e2e` first ("e" < "t"), plain
`pytest tests/` was **red**, not green.

**Confirmed pre-existing, not caused by this integration** — the identical
failure reproduces on the pre-integration baseline commit `e40f461` against a
fresh, fully-migrated disposable PostgreSQL. But since `test_tenant_writes.py`
is one of the files this integration touches, it was fixed here rather than left
broken: `run_writes()` now idempotently re-asserts the tenancy DDL at the top,
matching both migrations verbatim (so it cannot mask a genuine migration
defect), mirroring the same guard `test_tenancy_rls.py` already carried for
exactly this reason. Committed separately as `0178d3f`.

Correcting the earlier report: §4 above said these suites passed, which was true
per-file but overstated — they were verified individually, not in collection
order. That gap is what the gate caught. The verification below was re-run in
collection order on a freshly-migrated disposable PostgreSQL each time.

```
tests/test_engine_e2e.py + tests/test_tenant_writes.py (the failing order)  2 passed
tests/test_tenancy_rls.py + test_concurrent_dispatch.py + test_os_shell.py  3 passed
tests/test_sequence_engine.py + tests/test_signal_v2_bridge.py             4 passed
```

### Still-outstanding, and honestly stated

The same class of bug affects at least two suites this integration does **not**
touch. On a clean, fully-migrated PostgreSQL:

```
tests/test_sprint1_platform.py     FAILED  DependentObjectsStillExist:
tests/test_security_compliance.py  FAILED  cannot drop table opportunities
                                           because other objects depend on it
```

Both files are **byte-identical on `main` and on the branch**, and both fail
identically on the pre-integration baseline — verified directly, not assumed.
Cause is the same root issue: partial model-import lists mean `drop_all()`
doesn't know about every table that migrations created (e.g. `quotes`, which has
an FK into `opportunities`). This is the import-completeness item already logged
in `PRODUCTION_READINESS_2026-08-02.md`; it is a genuine CI-red condition that
should be cleared before relying on `pytest tests/` as a release gate.
`test_engine_e2e.py` already carries the fix pattern (a complete model-module
import list) if you want it applied across the rest.

I was also unable to run the **entire** suite end-to-end in this environment —
each shell call is capped at 45 seconds and the full run exceeds it. So "the
whole suite is green" is *not* a claim being made here; what was verified is
listed explicitly above.

### Dry-run enforcement, re-verified after the merge

- Both `transport=` call sites in `orchestrator.py` still pass `"dry_run"`
  literally (lines 73 and 167) — not a variable, not configurable at runtime.
- `delivery.py` registers **no** transport at import time beyond the built-in
  dry-run one.
- The Gmail / Microsoft 365 / SES adapters exist but are fail-closed behind
  opt-in env flags (`ENABLE_GMAIL_TRANSPORT`, `ENABLE_M365_TRANSPORT`) that are
  **not set**, and nothing calls their `try_register_*()` functions at startup.
- No SendGrid code path exists at all — only comments explaining why it's
  unsuitable.

**No real outreach was enabled by this merge.**

### Rollback

Single revert of the merge commit:

```
git revert -m 1 ca4981e
```

`-m 1` keeps the baseline parent. No migration ran and no data changed, so the
revert is complete on its own — nothing else needs undoing.
