# Integration Map — Candidate v4 (unified ABM + marketing + CRM), 2026-08-02

Full diff of `DRIP_unified_ABM_Marketing_CRM_v4_2026-08-02.zip` against the real
repo **as it stands after the v2 merge (`ca4981e`)**, not an older snapshot.
28 files differ; 1 file is new (a bundled copy of the earlier audit doc, not code).
`platform/`, `main.py`, `tenant_middleware.py`, `.github/workflows/ci.yml`, every
Alembic migration but one, and every router not listed are byte-identical.

Zip hygiene: no `.env`, database, dump, log, cache or test artifact; credential
scan (AWS/OpenAI/Slack key patterns, PEM blocks, DB URIs with embedded
credentials, generic secret assignments) found **no real secrets**. Two
`.env.example` files contain placeholders only. Nothing here requires credential
rotation.

**As with v2, this candidate was built from a snapshot predating some verified
fixes on `main`.** Ten of the 28 differing files are the candidate reverting work
already proven correct. Those are rejected below with the specific evidence,
rather than resolved silently.

## Legend
**Integrate** — new and correct · **Hand-merge** — new value + would drop
something · **Reject** — reverts a verified fix · **No-op** — cosmetic ·
**Change** — right idea, wrong implementation

| Candidate file | Decision | What / why | Migration? |
|---|---|---|---|
| `abm_platform/services/unified.py` | **Integrate** | Adds `growth_operations()`: one read model across accounts → signals → contactable people → active nurture → engaged → open pipeline, plus approval/task/failed-delivery queues and an explicit `controls` block (`real_delivery_enabled: False`, c-suite gate, consent gate). Contactable count correctly excludes suppression-list and denied/withdrawn-consent records. Purely additive. | No |
| `abm_platform/services/journeys.py` | **Integrate** | Journey send nodes now actually send: deterministic `uuid5` message id per enrollment+node (so a retry can't double-send), merge rendering, shared dry-run delivery, attribution touch, account rescore. Enrollment validates contactability and is idempotent. Branch conditions read real open/click `DeliveryEvent` rows instead of the previous hard-coded `False` — branches were structurally dead before. | No |
| `abm_platform/services/marketing.py` | **Integrate** | Campaign send is exactly-once per campaign/contact (deterministic id); merge fields rendered consistently; touches rescore the ABM account. Critically: a **c-suite recipient now creates a real approval draft** instead of being counted as sent, and the campaign stays `awaiting_approval` until every executive draft is released. `send_campaign` still defaults to `transport="dry_run"`. | No |
| `abm_platform/services/delivery.py` | **Integrate** | Inbound events now close the loop: delivery events trigger engagement rollup + account rescore, and hard bounce / complaint / spam / unsubscribe enforce `do_not_contact`, with complaint and unsubscribe also writing denied consent. Also fixes `unsubscribe` not being recognised alongside `unsub`. | No |
| `routers/unified.py`, `routers/journeys.py` | **Integrate** | `GET /dashboard/growth-operations` and `GET /journeys` (list with live enrollment counts) — the journeys screen previously had no way to read real journey definitions. Additive. | No |
| `routers/os_shell.py` | **Integrate** | Command dashboard, Signal Command Center, mobile nav, single-column responsive grids, overflow-safe tables, visible keyboard focus, skip-to-content, live status messaging, reusable empty/error states, auth failures routing to sign-in. Verified a strict superset: every line it removes is replaced by a better version, and it **retains** the v2 Approve/Pause/Resume error-surfacing merged earlier today. | No |
| `routers/bd_parity.py` | **Hand-merge** | Took the real change — `_audience_person_ids()` extracted so a new read-only `POST /mkt/audiences/preview` can answer "who would this reach" **without** creating a throwaway audience row on every click. Did not take the candidate's collapse of the seven-branch `if/elif` onto single lines. | No |
| `routers/signal_review.py` | **Hand-merge** | Took the new read-only `GET /signal-review/coverage` (channel-by-channel coverage for the command center). Did not take its deletion of the HMAC/replay-window rationale on `capture_webhook` — that comment documents a security decision. | No |
| `abm_platform/services/orchestrator.py` | **Hand-merge + Change** | Took the campaign-draft dispatch branch (releasing a c-suite campaign approval must complete the *campaign's* delivery, not a sequence's) and the contactability re-check hoisted above it. Kept the row-level `FOR UPDATE SKIP LOCKED` the candidate deletes, and kept the explanatory comments it strips. **Rewrote the tick lock** — see below. | No |
| — *(orchestrator, the tick lock)* | **Change — do not adopt as written** | The candidate holds a PostgreSQL **session** advisory lock on the SQLAlchemy `Session`. A session advisory lock belongs to the backend connection that took it; a `Session` returns its connection to the pool on commit, and this tick commits internally more than once. Measured on a disposable PostgreSQL: under two concurrent ticks the Session came back on a **different backend in 3 of 4 runs**, so `pg_advisory_unlock` ran on the wrong connection, returned `false`, and the lock was never released. Stranded locks pile up on idle pooled connections until every tick reports "another engine tick is already running" and **the engine silently stops dispatching** — output indistinguishable from an idle engine. Shipped instead: the lock is held on a dedicated connection pinned for the tick's duration (self-healing — a dead process closes the connection and PostgreSQL drops the lock). `tests/test_tick_lock.py` pins the exact property that failed. | No |
| `abm_platform/services/signal_v2_bridge.py` | **Reject** | Same regression as v2: strips the quality-gate hardening (`action_eligible=0`, `quality_decision='pass'`, completeness/materiality thresholds, pending-contradiction check), reverting to trusting `scoring_eligible=1` alone. That hardening was verified against real captured signal data. | — |
| `alembic/versions/d1a2b3c4e5f6_add_tenancy_and_rls.py` | **Reject** | Reverts to the `downgrade()` proven broken by an actual upgrade→downgrade→upgrade round trip (`InvalidTableDefinition: cannot drop inherited column` on partition children). | — |
| `tests/test_tenancy_rls.py` | **Reject** | Reverts the idempotent RLS DDL re-assertion and the captured-`DATABASE_URL` fix, both of which caused a **false pass** on the file's most important check. | — |
| `tests/test_tenant_writes.py` | **Reject** | Reverts today's order-independence fix; without it the file fails whenever it runs after `test_engine_e2e.py`, which collection order guarantees. | — |
| `tests/test_signal_v2_bridge.py` | **Reject** | Reverts a before/after table-existence comparison to an assertion that false-fails against an already-migrated shared PostgreSQL. | — |
| `tests/test_engine_e2e.py` | **Reject** | Its only addition (`import models_p11, models_p12`) is already a subset of the complete model-import list on `main`; taking the file would drop the rest. | — |
| `tests/test_ai_orchestrator.py` + `test_sprint2`…`test_sprint6` (6 files) | **Reject** | Still missing the pytest wrappers; without them `pytest -q tests/` silently runs zero of their ~120 checks. The candidate's own audit lists this as an unresolved blocker in its copy. | — |
| `config.py`, `routers/pipeline_ops.py` | **No-op** | Functionally identical; differences are a reordered method and deleted explanatory comments. | — |
| `Start DRIP Platform.bat`, `Start Dashboard.bat` | **No-op** | Both already bind `127.0.0.1`; only comment wording differs. | — |
| `CTO_DASHBOARD_AUDIT_2026-08-02.md` | **Skip** | Reference doc bundled in the zip, not a repo file. | — |

## Found by this integration's own test gate (not in the candidate)

| File | Change |
|---|---|
| `tests/conftest.py` | Imports every model module so `Base.metadata` is complete for all suites. Without it, `drop_all()` against a migrated PostgreSQL failed with `DependentObjectsStillExist` (`quotes.opportunity_id` → `opportunities`) in **four** suites: `test_sales_engagement`, `test_tracking_decision`, `test_sprint1_platform`, `test_security_compliance`. Confirmed pre-existing by reproducing on `main`. Imports-only — cannot mask a real defect. |
| `tests/test_platform_services.py` | Its attribution checks assert exact credit splits over exactly three touches, and broke once campaign sends began recording real attribution touches on the same fixture account. Moved to a dedicated account, and the new behaviour is now asserted directly rather than worked around. |
| `tests/test_tick_lock.py` (new) | 9 checks: mutual exclusion across three concurrent races, no overlap inside the tick body, **no advisory lock stranded**, later ticks not jammed, plus the SQLite process-lock path. |

## Net effect

16 files changed, 759 insertions, 48 deletions. **No schema change, so no new
Alembic migration.** Zero files reverted to an older state.
