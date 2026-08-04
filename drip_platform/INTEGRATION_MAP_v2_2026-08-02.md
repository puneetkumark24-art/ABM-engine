# Integration Map — Candidate v2 vs. current DRIP repo (2026-08-02)

Full diff of `DRIP_CTO_dashboard_hardened_candidate_v2_2026-08-02.zip` against the real
repo as it stands right now (after today's earlier Codex-merge + punch-list rounds),
not against an old snapshot. 22 files differ; everything else — including
`platform/`, `main.py`, `abm_platform/services/delivery.py`, all Alembic migrations
except one, and every router not listed below — is byte-identical. No `.env`,
database, dump, log, or cache file is present in the candidate zip; `_signal_v2_backups/`
and `_tmp_orig_bridge_test/` in the zip are copies of this session's own earlier
scratch/backup folders, not candidate content, and are excluded from integration.

**Important finding, stated plainly per your instruction to report conflicts rather
than silently resolve them:** this candidate was built from a snapshot that predates
some of today's later, empirically-verified fixes. Five of the 22 differing files are
the candidate *reverting* real bugs that were found and fixed (with evidence) earlier
today — most seriously, the signal export quality gates and a proven-broken Alembic
downgrade path. Those are rejected below, with the specific evidence cited. This
resolves the conflict by keeping the newer, verified DRIP functionality, per your
priority #2 — flagging it here rather than choosing silently.

## Legend
- **Integrate** — genuinely new and correct; not in the current repo.
- **Reject (regression)** — candidate reverts a fix already verified working today.
- **No-op (cosmetic)** — functionally identical; not worth the diff churn.

| Candidate file | DRIP file | Proposed change | Conflict risk | Migration? |
|---|---|---|---|---|
| `tenant_middleware.py` | same | **Integrate.** Method-aware authorization: GET requires `crm.read`, mutating methods (POST/PUT/PATCH/DELETE) require `crm.write`. Adds explicit scope coverage for `/organizations`, `/persons`, `/signals`, `/opportunities`, `/sales`, `/signal-review`, `/dev`, `/compliance`, `/workflow` (previously uncovered — any authenticated principal could hit them regardless of scope). Fixes a real route-boundary bug: old `path.startswith(prefix)` matched `/crmevil` against `/crm`; new logic requires an exact match or a `/`-bounded prefix. | Low — single file, one call site, backward-compatible signature (`method` param defaults to `"GET"`). | No |
| `tests/test_tenant_writes.py` | same | **Integrate.** New assertions exercising the above (route-boundary, read-vs-write scope, admin-only surfaces). | Low — additive test code only. | No |
| `abm_platform/services/orchestrator.py` | same | **Integrate (partial — 2 of 3 changes).** (1) Duplicate-held-draft prevention: a c-suite enrollment stays "due" while awaiting human review, so every tick was generating another pending draft for the same person/step — now skips if a `pending`/`approved` draft already exists for that person+step. (2) Human-approved dispatches now feed their `org_id` into the same engagement-rollup/rescore loop as automatic sends (previously only automatic sends triggered a rescore). (3) Whole-tick advisory/process lock — **not** integrated as-is; see note below. | Medium — touches the file I already modified for row-level locking; merging by hand, not overwriting. | No |
| — (orchestrator, item 3) | — | **Modify, not adopt verbatim.** Candidate wraps the entire tick in `pg_try_advisory_lock`/`pg_advisory_unlock` (session-scoped) with a `threading.Lock` fallback on SQLite. Session-scoped advisory locks are tied to whatever DBAPI connection the SQLAlchemy `Session` currently holds; `_dispatch_human_approved` and `run_tick` both call `db.commit()` internally, and a `Session` is not guaranteed to keep the same pooled connection across a commit under real concurrent load — if it doesn't, `pg_advisory_unlock` at the end could silently fail to release the *actual* lock, leaving a connection permanently "stuck" in the pool and jamming all future ticks that happen to check it out. This needs to be verified empirically (real concurrent threads, real Postgres, multiple internal commits) before being trusted, not accepted on the strength of its own comment. My existing row-level `FOR UPDATE SKIP LOCKED` protection on the approved-drafts query is already proven (previous session: reproduced the race with the lock removed, confirmed the fix prevents it, under real concurrent threads). Plan: keep that as primary protection, and only add the tick-level lock on top if it passes the same bar. | Medium — concurrency correctness, needs its own test before trusting. | No |
| `routers/os_shell.py` | same | **Integrate.** `apApprove`/`sqePause`/`sqeResume` currently fire-and-forget — a 409 from the pause/resume validation I added earlier today was silently swallowed by the UI (button appeared to "succeed" while the backend rejected it). Candidate wires these to check `r.ok` and alert on failure, plus clarifies that approval dispatches on the *next* engine cycle, not immediately. | Low — 6-line additive diff to existing JS. | No |
| `tests/test_engine_e2e.py` | same | **Integrate (merge, not replace).** Candidate adds one new assertion — "repeated tick does not duplicate held draft" — exercising the orchestrator fix above. Candidate's copy of this file is otherwise *missing* my existing import-completeness fix (see reject list). Plan: keep my version, add just the new assertion. | Low. | No |
| `abm_platform/services/signal_v2_bridge.py` | same | **Reject (regression).** Candidate strips the quality-gate hardening merged earlier today — drops the `action_eligible=0`, `quality_decision='pass'`, completeness/materiality thresholds, and pending-contradiction check, reverting to "trust `scoring_eligible=1` alone." That hardening was verified against real captured signal data (all 3 currently-eligible signals still pass under the stricter gate). Taking this file would silently re-widen signal export eligibility. | N/A — not adopting. | No |
| `alembic/versions/d1a2b3c4e5f6_add_tenancy_and_rls.py` | same | **Reject (regression).** Candidate's `downgrade()` is the pre-fix version that tries to `DROP COLUMN tenant_id` directly on partition child tables (`metric_events_default`, etc.) — proven broken today by actually running an upgrade→downgrade→upgrade round trip against a disposable Postgres (`InvalidTableDefinition: cannot drop inherited column`). My current version skips partition children (their parent's drop cascades automatically) and passes the same round trip cleanly, twice. | N/A — not adopting. | No |
| `.github/workflows/ci.yml` | same | **Reject (regression).** Candidate lacks `DRIP_ALLOW_PG_TESTS: "1"`, which today's work added specifically so CI's disposable Postgres service actually runs the RLS-isolation proof instead of silently skipping it (verified: 15/15 checks including all 5 RLS checks, using the exact CI sequence). | N/A — not adopting. | No |
| `tests/test_tenancy_rls.py` | same | **Reject (regression).** Candidate reverts two proven fixes from today: (1) the idempotent re-assertion of `organizations.tenant_id`/RLS policy before seeding (without it, any other test's `Base.metadata.drop_all()` silently wipes the migration-only columns and the RLS half breaks depending on file order); (2) reading `DATABASE_URL` from a value captured once by `conftest.py` rather than live from `os.environ` (without it, `test_signal_v2_bridge.py` mutating that env var for its own isolated DB caused this suite's RLS checks to silently report "skipped" while the test still went green — a false pass on the single most important check in the file). Both reproduced and fixed today with direct evidence. | N/A — not adopting. | No |
| `tests/test_signal_v2_bridge.py` | same | **Reject (regression).** Candidate reverts the before/after table-existence comparison back to an unconditional "table must not exist" assertion, which fails against an already-`alembic upgrade head`-ed shared Postgres (where the table legitimately pre-exists from migration `s6e8f0a2c4d5`) — reproduced today as a real false failure before fixing it. | N/A — not adopting. | No |
| `tests/test_ai_orchestrator.py`, `test_sprint2_agents.py`, `test_sprint3_bank_intelligence.py`, `test_sprint4_tier_c.py`, `test_sprint5_copilot.py`, `test_sprint6_crm_notify.py` (6 files) | same | **Reject (regression).** Candidate lacks the pytest wrapper functions added today. Without them, CI's `pytest -q tests/` silently collects and runs zero of these files' ~120 real checks (proven earlier: they ran, but were invisible to plain pytest). The candidate's own audit report explicitly lists this as an *unresolved* blocker in their copy ("Make the script-style test collection pytest-safe... remains a blocker") — consistent with what's found here. | N/A — not adopting. | No |
| `config.py` | same | **No-op.** Functionally identical to current DRIP (`validate_runtime()` already present and correct); candidate only reorders methods and shortens a docstring. | None. | No |
| `routers/pipeline_ops.py` | same | **No-op.** Functionally identical; candidate is missing an explanatory comment, no logic difference. | None. | No |
| `routers/signal_review.py` | same | **No-op.** Functionally identical; candidate is missing an explanatory comment, no logic difference. | None. | No |
| `Start DRIP Platform.bat`, `Start Dashboard.bat` | same | **No-op.** Both already bind `127.0.0.1` in the current repo; candidate differs only in comment wording. | None. | No |
| `CTO_DASHBOARD_AUDIT_2026-08-02.md` (candidate's own copy of the earlier v1 audit) | — | **Not code — skip.** Reference document bundled inside the zip, not a repo file to integrate. | None. | No |
| `platform/` (26-module registry) | same | **Already identical** — confirmed byte-for-byte match (only difference was a stale `__pycache__`). No action. | None. | No |

## Net effect of integration

5 files touched (`tenant_middleware.py`, `orchestrator.py`, `os_shell.py`,
`test_tenant_writes.py`, `test_engine_e2e.py`), all additive/merged by hand rather
than overwritten. Zero files reverted to an older state. No schema change, so **no
new Alembic migration is required** for this integration.
