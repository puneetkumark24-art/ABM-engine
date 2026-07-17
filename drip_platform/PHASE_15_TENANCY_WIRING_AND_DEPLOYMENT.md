# Phase 15 — Tenancy Wired Through the App (P0-A.2) + Deployment Package

Completes everything buildable without external credentials: request-scoped
tenancy across the whole API, and a one-command deployment of the full stack.

## Result: 237/237 checks green on PostgreSQL

| Suite | Checks |
|---|---|
| P0-A.2 tenant writes + middleware (new) | 11/11 |
| (all Phase 13/14 suites) | 226/226 |
| **Total** | **237/237** |

Plus: deployment package validated — compose parses, entrypoints lint clean,
and the worker+scheduler processes drive the engine end-to-end (scheduler
enqueues 3 jobs → worker pool processes 3 → 3 drafts + 3 outbox events).

## P0-A.2 — Tenancy wired through the whole app (no per-model edits)

Instead of editing `tenant_id` into ~75 ORM classes, the isolation is enforced
by the database and wired at one choke point:

1. **Migration `g4d6e8f0a2b3`** — every `tenant_id` column now DEFAULTs to
   `COALESCE(current_setting('app.current_tenant')::uuid, bootstrap)`. So **any
   ORM insert that omits tenant_id — i.e. all existing code, unchanged — is
   automatically stamped with the session's tenant.** Proven: an
   `Organization()` inserted under a tenant-A session gets `tenant_id = A`
   (not bootstrap); under B gets B.
2. **`tenant_middleware.py`** — verifies the JWT per request and stashes the
   tenant in a contextvar; `AUTH_ENFORCED` gates rejection; public `/t/*`,
   `/p/*`, `/health` exempt. Proven: token → tenant in context; enforced mode
   returns 401 for missing/bad tokens on protected routes and 200 on public
   ones.
3. **`database.get_db`** — reads that contextvar and binds the RLS GUC for the
   session, resetting on close (no pooled-connection leakage). **Every route
   using `Depends(get_db)` is now tenant-scoped without touching the route.**
4. **`main.py`** — mounts `TenantMiddleware`.

Net: reads AND writes are tenant-isolated by Postgres, enforced for a
non-superuser role, with the app unchanged at the query level. (Read isolation
proven as `app_rw`; superuser sessions intentionally bypass RLS — which is why
the runtime connects as `app_rw`.)

## Deployment package (`deploy/`)

One command stands up the enterprise stack:

```bash
cp deploy/.env.example deploy/.env      # edit secrets
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build
```

- **`Dockerfile`** — one slim image (python 3.12, libpq, tini, non-root user)
  for api/worker/scheduler.
- **`docker-compose.yml`** — `postgres` (RLS), `redis`, `api`, **`worker` ×2**
  (SKIP-LOCKED-safe horizontal scaling), `scheduler`; healthchecks + volumes.
- **`entrypoint_api.sh`** — wait-for-db → `alembic upgrade head` (superuser) →
  `bootstrap.sql` (create `app_rw` + grants) → uvicorn **as `app_rw`**.
- **`bootstrap.sql`** — the non-superuser runtime role + grants + default
  privileges for future tables.
- **`worker_main.py`** — registers handlers, runs the durable job loop.
- **`scheduler_main.py`** — beat: enqueue due steps, relay outbox, retry sends,
  fire scheduled campaigns, provision next month's partition.
- **`.env.example`**, **`requirements-deploy.txt`**, **`README_DEPLOY.md`**.

The two-URL security model is explicit: **migrations/bootstrap use the superuser;
the runtime uses `app_rw`** so RLS actually applies. `AUTH_ENFORCED=true`,
`dry_run`-only sending, and PDPL still gate real outreach.

## Where P0 stands now — everything buildable is built

| P0 item | Status |
|---|---|
| A · tenancy + RLS + auth mechanism | ✅ done, PG-proven |
| A.2 · wired through the app (writes + reads + middleware) | ✅ done, PG-proven |
| B · async substrate (queue, SKIP LOCKED, outbox, worker, scheduler) | ✅ done, PG-proven |
| C · O(N)/O(N²) hot paths → set-based SQL | ✅ done, PG-proven |
| D · UUIDv7 + partitioning + set-based analytics | ✅ done, PG-proven |
| Deployment package (Docker/compose/worker/scheduler) | ✅ done, validated |

**All 237 checks pass on real PostgreSQL 16; the full 22-migration chain applies
clean; the containerized worker+scheduler drive the engine end to end.**

## What genuinely cannot be done from here (needs YOU / infra)

These are not code — they need your accounts, credentials, and sign-off:
1. **Run it** on your infrastructure (a host/VM/K8s) — `docker compose up`.
2. **Real email**: verify a Decimal sending domain (DKIM/SPF/DMARC), warm an IP,
   set SES creds, flip a campaign off `dry_run`.
3. **Real enrichment data**: contract Apollo/Clay or equivalent (the data moat).
4. **PDPL legal sign-off** before any real outreach to KSA contacts.
5. **P1 infra upgrades** (Kafka/ClickHouse/OpenSearch/Temporal/OIDC gateway/
   secrets vault) — the review's Part J, when volume demands them.

The platform code is now enterprise-shaped, multi-tenant, authenticated,
async, partition-ready, and containerized — verified against real Postgres. The
remaining steps are deployment and business decisions, which is exactly where a
software build should hand off.
