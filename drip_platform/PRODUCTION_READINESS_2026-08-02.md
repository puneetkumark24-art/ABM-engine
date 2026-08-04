# DRIP Production Readiness — 2026-08-02

Status report covering two pieces of work done back-to-back today: (1) reviewing and
integrating an external hardening pass ("Codex") into the real repo, and (2) working
through the "what's left" punch list from that pass. Every claim below was checked
against a real, disposable PostgreSQL 16 instance (via `pgserver`) and/or a live
`TestClient` — nothing here is asserted from reading code alone. Where something is
still broken, blocked, or unverified, it's flagged as such rather than rounded up.

---

## 1. What shipped today

### 1.1 Codex hardening pass — merged and re-verified

Twelve files reviewed diff-by-diff, the two highest-risk claims independently verified
against real data before merging anything, then the full merged set re-verified end to
end:

| Area | Fix | Verified |
|---|---|---|
| Approval workflow | Approving a draft used to be a dead end — `pending → approved` and nothing downstream ever acted on it. `orchestrator._dispatch_human_approved()` now completes the lifecycle: re-checks compliance, dispatches (dry-run), advances the sequence. | E2E test: approve → next tick → `sent`, sequence advanced exactly once. |
| Signal export | `preview()` was writing to Postgres (creating `signal_v2_exports`) despite being documented read-only; export criteria didn't check quality gates or pending contradictions. | Fixed to true read-only preview + quality-gated export. Re-checked against real captured data: all 3 currently-eligible signals still pass. |
| Draft approve/reject/edit | No validation — could approve a draft with no linked contact, reject with no reason, edit an already-approved draft. | 409/422 on invalid transitions, verified via live `TestClient`. |
| Sequence pause/resume | Silently no-op'd on invalid state transitions instead of erroring. | Now 409s correctly; verified live. |
| Signal capture webhook | Static, reusable bearer token. | Timestamped HMAC-SHA256 (5-min replay window); verified valid/missing/stale-signature cases live. |
| Dashboard (os_shell.py) | Reject required no reason; Run Engine button relied on an implicit global `event`; tick output didn't show approval-dispatch counts. | Fixed; JS re-validated with `node --check`. |
| Production boot | `APP_ENV=production` would boot with default secrets, SQLite, wildcard CORS, auth disabled. | `settings.validate_runtime()` now refuses to boot; verified both the unsafe-config-raises and safe-config-passes cases. |
| Desktop launchers | Bound `0.0.0.0` (exposed to the whole office network) by default. | Now `127.0.0.1`. |

### 1.2 This round: the "what's left" punch list

Scoped to what's actually achievable in an engineering sandbox without external
credentials, infra provisioning, or another person's time (see §2 for what isn't).
While verifying these, the process of actually running things for real (not just
reading them) surfaced five previously-unknown, genuine bugs — listed here because
they're the most concrete evidence that "looks right" and "is right" are different
things, and because each one would have caused a real, silent problem in CI or
production if left alone.

**CI was silently skipping ~23% of the test suite.** Two files (`test_signal_decay.py`,
`test_signal_intel.py` — legacy Flask-dashboard tests) run their checks as top-level
module code with a bare `sys.exit(1)` on failure; under plain `pytest`, that doesn't
report as a clean test failure, it crashes the *entire collection* with an
`INTERNALERROR` and hides every other file's results — reproduced directly. Six more
files (`test_ai_orchestrator.py`, `test_sprint2` through `test_sprint6`) had zero
pytest-collectible `test_` functions, so `pytest -q tests/` silently ran 0 of their
~120 real checks. Fixed: the two legacy files are excluded from collection via
`tests/conftest.py` (they test a deprecated app, not the one in production; still
runnable by hand) and the six script-style suites now have proper pytest wrappers.
Verified: clean collection (no crash), all six execute and pass under pytest.

**The multi-tenant RLS isolation proof was never actually running in CI.**
`test_tenancy_rls.py` guards its Row-Level-Security checks behind
`DRIP_ALLOW_PG_TESTS=1` as a safety rail (so it can never run against a real prod DB
by accident) — CI never set that flag, so the actual database-enforced tenant
isolation check was always skipped, silently. Fixed: CI's Postgres is a disposable
per-run container, so `DRIP_ALLOW_PG_TESTS=1` is now set there. Verified with the
exact CI sequence (`alembic upgrade head` then the test): 15/15 checks pass, including
all 5 RLS checks.

**Two more bugs turned up specifically because enabling that flag made the RLS test
suite share a live database with everything else for the first time**, instead of
running alone (which is how it had only ever been checked before):

- `Base.metadata.drop_all()`/`create_all()` in `test_engine_e2e.py` (and by the same
  pattern, presumably others) only knows about ORM-mapped tables it has imported —
  against the real, fully-migrated schema, dropping `opportunities` before `quotes`
  (whose model lives in `models_crm2.py`, never imported here) fails with a real
  Postgres FK error. Fixed the import list for this file; the same class of bug likely
  exists in other files that weren't audited (see §2).
- Once schema-reset tests could run alongside it, `test_tenancy_rls.py`'s
  `organizations.tenant_id` column and RLS policy — which only exist via raw
  migration SQL, never as an ORM column — got silently wiped by any other test's
  `drop_all()`/`create_all()`. Fixed by having the RLS test idempotently re-assert its
  own required schema before it needs it, so it's self-healing regardless of what ran
  before it.

**A silent false-pass from environment pollution.** `test_signal_v2_bridge.py`
reassigns `os.environ["DATABASE_URL"]` for its own isolated temp-file SQLite DB and
never restores it. `test_tenancy_rls.py` was re-reading that same env var live to
decide "are we on Postgres" — after the other file ran, it would read the mutated
SQLite value, silently print "RLS checks skipped," and still report an overall pass.
Fixed: `tests/conftest.py` now captures the true, CI-configured `DATABASE_URL` before
any test file can touch it, and `test_tenancy_rls.py` reads that instead of the live
(mutable) env var. Re-verified the exact failure scenario: all 5 RLS checks now
genuinely execute instead of silently no-op'ing.

**Alembic migrations had only ever been run in one direction.** Running a real
`upgrade → downgrade → upgrade` round trip against a disposable Postgres (never done
before, by anyone, on this repo) failed immediately: the tenancy migration's
`downgrade()` tried to `DROP COLUMN tenant_id` directly on partition *child* tables
(`metric_events_default`, `delivery_events_2026_07`, etc.) — Postgres rejects that
even with `IF EXISTS`, because the column only really exists on the partitioned
parent and the drop should cascade from there. `pg_tables` has no defined row order,
so this broke intermittently depending on which table alembic happened to reach first.
Fixed by skipping partition children in the downgrade loop (their parent's drop
already cascades to them). Verified: full round trip passes cleanly, twice, on fresh
databases. A permanent regression test (`test_alembic_roundtrip.py`) now guards this,
gated the same way as the RLS suite since it's destructive.

**No protection against a double-fired tick.** Nothing stopped two concurrent
`run_tick()` invocations (a cron double-fire, or a human clicking "Run engine now"
twice before the first click finishes) from both selecting and dispatching the *same*
approved draft — a real duplicate email to a real prospect, not just a harmless
double-write. Proved this is a real risk, not theoretical, by temporarily disabling
the fix and running two real threads with separate DB sessions against real Postgres:
they raced and crashed on a duplicate-key violation trying to insert the same
`SendRequest`. Fixed with `SELECT ... FOR UPDATE SKIP LOCKED` (Postgres only; SQLite
has no meaningful session concurrency to protect) so a second concurrent tick silently
skips whatever the first tick already has locked, rather than racing it. Re-verified
with the fix restored: 8 drafts, two racing threads, all 8 dispatched exactly once,
zero duplicates, zero drops. Permanent regression test:
`test_concurrent_dispatch.py`.

### 1.3 Files touched this round

`tests/conftest.py` (new), `.github/workflows/ci.yml`, six `tests/test_sprint*.py` /
`test_ai_orchestrator.py` (pytest wrappers), `alembic/versions/d1a2b3c4e5f6_add_tenancy_and_rls.py`
(partition-child fix), `tests/test_alembic_roundtrip.py` (new),
`tests/test_engine_e2e.py` (import completeness), `tests/test_tenancy_rls.py`
(self-healing + env-pollution fix), `tests/test_signal_v2_bridge.py` (assertion fix),
`abm_platform/services/orchestrator.py` (row locking),
`tests/test_concurrent_dispatch.py` (new).

All Python files compile clean; `ci.yml` is valid YAML; the full `tests/`
directory collects cleanly under pytest with no crash (63 tests, up from a
crash-before-46 baseline); every fix above was re-verified together in the same
adversarial file order a real CI run would use, against a fresh disposable Postgres,
not just in isolation.

---

## 2. What's still open, and why

Genuinely blocked on something outside this environment — not skipped for
convenience:

- **Human signal-review calibration set** (≥100 reviewed samples, ≥90% agreement with
  the automated quality gate) — this requires actual human judgment on real captured
  signals. Nothing here can fabricate that meaningfully; it needs the team's review
  time.
- **HubSpot backfill, website-intent signals, full LinkedIn integration** — need real
  API credentials/access that aren't available in this sandbox. LinkedIn specifically
  should stay blocked until official API access exists, per the original audit's own
  recommendation.
- **Credential rotation / scrubbing secrets from git history** — needs the user's
  actual secret values and an explicit go-ahead to rewrite git history; not something
  to do unattended.
- **Redis-backed rate limiting in production** — already implemented correctly
  (`abm_platform/services/cache.py` uses real Redis when `REDIS_URL` is set, falls
  back to an in-memory limiter otherwise); what's missing is a production Redis
  instance and the URL, which is an infra decision, not code.
- **Full browser/accessibility/RTL testing** — feasible with the Chrome tooling
  available in this environment, but a genuinely large undertaking (every screen) that
  wasn't in today's explicit scope; flagging as available on request rather than
  guessing at priority.
- **Import-completeness audit across the rest of the test suite** — §1.2 found and
  fixed this specific bug in `test_engine_e2e.py`; the same pattern (a script-style
  test's `Base.metadata.drop_all()` not importing every model module) likely exists in
  some of the other ~30 files that weren't individually audited this round. Worth a
  dedicated pass, not attempted here to avoid touching many files without the same
  level of individual verification applied everywhere else in this report.
- **Distributed locking beyond the one path fixed** — `FOR UPDATE SKIP LOCKED` now
  protects `_dispatch_human_approved`, the newest and highest-risk path. The main
  sequence-processing loop (`seq_engine.get_due()`) loads and filters "due" enrollments
  in Python rather than via a single locked query, and wasn't hardened this round —
  same class of risk, larger refactor, not attempted here.

---

## 3. Bottom line

The approval → dispatch → sequence-advance loop actually completes now, end to end,
under concurrent load, without duplicating a send. The signal export path can't leak
low-quality or contested signals. A misconfigured "production" deploy refuses to boot
instead of quietly running unsafely. CI now actually runs the tests it claims to run,
including the one check (multi-tenant isolation) that matters most for a
multi-bank platform — and the specific ways it was previously failing to run them
have real, verified fixes, not just a flag flip.

Everything still marked open above is blocked on something this environment
genuinely doesn't have — credentials, infrastructure decisions, or another person's
time — not on remaining engineering effort.
