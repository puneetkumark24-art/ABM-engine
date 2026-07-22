# DRIP — Deployment

One command brings up the whole enterprise stack: Postgres (RLS), Redis, the
API, a horizontally-scalable worker pool, and the scheduler.

## Quick start

```bash
cd drip_platform
cp deploy/.env.example deploy/.env      # then edit the secrets
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build
# API on http://localhost:8000  ·  docs at /docs  ·  health at /health
```

## What happens on `up`

1. **postgres** + **redis** start; compose waits for their healthchecks.
2. **api** entrypoint: waits for the DB → `alembic upgrade head` (as the
   superuser) → runs `bootstrap.sql` to create the non-superuser **`app_rw`**
   role + grants → starts uvicorn **connecting as `app_rw`** (so RLS applies).
3. **worker** (×2 replicas) registers job handlers and consumes the durable
   queue with `FOR UPDATE SKIP LOCKED` — safe to scale to any N.
4. **scheduler** ticks every 15s: enqueue due sequence steps, relay the outbox,
   retry failed sends, fire scheduled campaigns, provision next month's
   partition.

## Security posture (why the two DB URLs)

- `MIGRATE_DATABASE_URL` = **postgres superuser** — used only for migrations +
  role bootstrap (needs DDL). Superusers bypass RLS, which is exactly why the
  app must NOT use it at runtime.
- `DATABASE_URL` = **`app_rw` (non-superuser)** — the runtime connection for
  api/worker/scheduler. RLS row-isolation only takes effect for non-superusers.
- `AUTH_ENFORCED=true` — the API rejects unauthenticated calls on protected
  routes; public tracking (`/t/*`) and landing (`/p/*`) paths stay open.
- `JWT_SECRET`, `MANDRILL_WEBHOOK_KEY`, DB passwords come from `.env` — replace
  with a real **secrets manager** (Vault/SSM) in production; never commit `.env`.

## Scaling knobs

- **Workers:** `deploy.replicas` on the `worker` service (SKIP LOCKED makes it
  safe). Add more when the `jobs` backlog grows.
- **API:** `WEB_CONCURRENCY` (uvicorn workers) + run multiple `api` replicas
  behind a load balancer.
- **DB:** add a read replica + PgBouncer (compose is single-node dev; production
  uses managed Postgres or a StatefulSet with PITR).

## Going to production (beyond this compose)

This compose is the **single-host / staging** shape. For the full target
architecture (Kafka/Redpanda, ClickHouse/Timescale, OpenSearch, Temporal, HA
Postgres, OIDC gateway, object storage), see `PRODUCTION_READINESS_REVIEW.md`
Part J. The service boundaries here map 1:1 onto that design — the queue swaps
to Kafka, the scheduler's journey logic moves to Temporal, analytics reads move
to the warehouse — without changing the domain code.

## Enabling real email (deliberate, off by default)

1. Verify a sending domain (DKIM/SPF/DMARC) and warm an IP.
2. Set `ENABLE_SES_TRANSPORT=true`, `AWS_SES_REGION`, `SES_FROM`, add `boto3` to
   `requirements-deploy.txt`, and provide AWS creds.
3. Register the SES transport (`delivery_ext.try_register_ses()` at worker boot)
   and switch a campaign's transport off `dry_run`. Until all of that, **nothing
   sends** — the platform is safe to run against real data in intelligence mode.

**Alternative: Mailchimp Transactional (Mandrill)**, ported from the legacy
`decimal_abm` system (AI Intelligence Layer Sprint 4) as the native Marketing
engine's own send path — not an external CRM bridge (HubSpot stays out
entirely per the 2026-07-21 decision to build CRM/Marketing natively). Set
`ENABLE_MANDRILL_TRANSPORT=true`, `MANDRILL_API_KEY`, `MANDRILL_FROM_EMAIL`,
`MANDRILL_FROM_NAME`, then call `delivery_ext.try_register_mandrill()` at
worker boot and switch a campaign's transport to `mandrill`. Same
inert-until-opted-in guarantee as SES.

## Files
`Dockerfile` · `docker-compose.yml` · `entrypoint_api.sh` · `bootstrap.sql` ·
`worker_main.py` · `scheduler_main.py` · `requirements-deploy.txt` · `.env.example`
