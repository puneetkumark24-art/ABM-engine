# Phase 13 / P0-A — Multi-Tenancy (RLS) + Authentication + Webhook Signatures

Closes the two production-readiness **showstoppers** from the review (BOMB 1: no
tenancy; BOMB 2: no auth) at the foundation level, proven on real PostgreSQL.

## Result

**15/15 P0-A checks on PostgreSQL 16**, and the existing suites still pass under
RLS (**test_platform_services 53/53, test_engine_e2e 30/30**) — proving tenant
isolation is enforced by the database *without breaking* tenant-unaware code
during rollout.

| Check group | Result |
|---|---|
| RLS isolation (tenant A cannot read tenant B, as a **non-superuser** role) | ✓ |
| RLS permissive when tenant context unset (gradual rollout) | ✓ |
| RLS role is genuinely non-superuser (so RLS actually applies) | ✓ |
| JWT: tenant+scopes round-trip, wildcard scopes, deny ungranted | ✓ |
| JWT: tampered / expired / wrong-secret tokens rejected (401) | ✓ |
| Webhook: valid HMAC accepted, forged rejected, no-secret fails closed | ✓ |
| Regression: existing engines under RLS | ✓ 83/83 |

## What was built

### 1 · Multi-tenancy with Postgres Row-Level Security (BOMB 1)
- **`models_tenant.py`** — `Tenant` root + `BOOTSTRAP_TENANT_ID` (all pre-tenancy
  rows are backfilled here → non-destructive).
- **Migration `d1a2b3c4e5f6`** (Postgres-only, SQLite unaffected): creates
  `tenants`, then for **every** table in `public` (introspected live, 76 tables)
  adds `tenant_id uuid` (defaulting existing rows to bootstrap), enables **and
  FORCEs** RLS, and installs a `tenant_isolation` policy:
  ```sql
  USING ( coalesce(current_setting('app.current_tenant', true), '') = ''   -- unset ⇒ permissive
          OR tenant_id::text = current_setting('app.current_tenant', true) )
  ```
- **`tenancy.py`** — `set_tenant()` / `tenant_session()` set the GUC
  **transaction-locally** (`set_config(..., true)`) — the correct pattern under
  connection pooling (no cross-request leakage). Every query is then
  auto-scoped; no manual `WHERE tenant_id=` anywhere.
- **The security model:** the app connects as a **non-superuser role
  (`app_rw`)**, because superusers bypass RLS. Verified in the test that
  `app_rw` is non-superuser and that isolation holds for it.

**Why permissive-when-unset:** a deliberate gradual-rollout aid. Existing
tenant-unaware code (and the 171 prior tests) runs without setting the GUC and
keeps seeing its data (all in the bootstrap tenant). Tightening to **strict +
`WITH CHECK`** (unset ⇒ see nothing; inserts must match tenant) is the P0-A.2
follow-up, done once every caller sets tenant context via `tenant_db_for`.

### 2 · Authentication + Authorization (BOMB 2)
- **`auth.py`** — self-contained **HS256 JWT** (stdlib only, no new dep):
  `issue_token`, `verify_token`, `Principal` (tenant_id + scopes with `crm.*`
  wildcards), and FastAPI dependencies `current_principal`, `require_scope(...)`,
  and **`tenant_db_for`** — the one dependency real routes should use: it
  authenticates AND opens a tenant-scoped DB session in one step. In production
  the signing moves to an OIDC provider (Keycloak/Cognito) behind the gateway;
  this interface is unchanged.
- Secret from `JWT_SECRET` (env → secrets manager in prod), not a checked-in key.

### 3 · Webhook signature verification (BOMB 2, delivery)
- **`webhook_security.py`** — `verify_hmac_sha256` (generic), `verify_mandrill`
  (exact Mandrill HMAC-SHA1 scheme), `verify_ses_sns` (returns False until the
  SNS cert path is wired — **fails closed**, nothing trusted by default). Stops
  the forged-bounce → false-suppression attack.

## How to apply on your machine

```bash
cd drip_platform
# 1. create the non-superuser app role (ops step, once):
psql -c "CREATE ROLE app_rw LOGIN PASSWORD '…' NOSUPERUSER;"
# 2. migrate (adds tenant_id + RLS to every table):
alembic upgrade head            # -> d1a2b3c4e5f6
# 3. point the app's DATABASE_URL at the app_rw role (NOT postgres/superuser)
# 4. set JWT_SECRET and MANDRILL_WEBHOOK_KEY from your secrets manager
python tests/test_tenancy_rls.py    # 15/15 on Postgres
```

## What this does NOT yet do (honest — the P0-A follow-ups)
1. **Wire `tenant_db_for` into every route.** The dependency exists and is
   proven; applying it across all ~14 routers (and adding `tenant_id` to the ORM
   models so the app writes it explicitly) is mechanical follow-up. Until then
   routes remain unauthenticated — **do not expose the API publicly yet.**
2. **Tighten RLS to strict + WITH CHECK** once all callers set tenant context.
3. **Real OIDC + gateway + rate limiting + secrets vault** (the review's full
   BOMB-2 fix) — this phase delivers the enforcement *mechanism*; the gateway is
   the deployment wrapper.
4. Per-tenant unique constraints (e.g. `organizations.canonical_name` →
   `(tenant_id, canonical_name)`).

## Files
`models_tenant.py` · `tenancy.py` · `auth.py` · `webhook_security.py` ·
`alembic/versions/d1a2b3c4e5f6_add_tenancy_and_rls.py` · `tests/test_tenancy_rls.py`.

## Review posture change
Security mechanism moves from **absent** to **built and DB-proven**; the number
improves once it's wired into every route and fronted by a gateway. This is the
correct first P0 step — the review said tenancy must come first because every
other fix builds on the key structure, and it now exists and is enforced.
