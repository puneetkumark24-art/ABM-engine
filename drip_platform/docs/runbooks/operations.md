# DRIP Operations Runbook (Sprint 10)

On-call entrypoint. Every alert in `deploy/observability/alerts.yml` links to a
section here.

## api-down
1. Confirm scope: `kubectl -n drip get pods` — are API replicas CrashLooping?
2. Check recent deploy: `kubectl -n drip rollout history deploy/drip-api`.
3. If a bad release: `kubectl -n drip rollout undo deploy/drip-api`.
4. Verify recovery on `/health/live` then `/health/ready`.

## db-unreachable
1. `/health/ready` returns 503 when the DB probe fails.
2. Check managed Postgres status + connection count (RLS role `app_rw`).
3. If connection exhaustion: scale down workers (HPA min), recycle API pods.
4. Failover is managed (multi-AZ). Confirm the writer endpoint resolved.

## elevated-errors
1. Identify the failing route: `drip_requests_total{status=~"5.."}` by `path`.
2. Correlate with `request_id` in structured logs (`drip.http`).
3. Roll back the most recent deploy if the spike aligns with it.

## latency
1. Check in-flight gauge + DB slow queries.
2. Confirm partition pruning on event tables (metric/delivery/web_events).
3. Scale API replicas / raise HPA ceiling if CPU-bound.

## worker-backlog
1. `drip_jobs_pending` high → workers not draining.
2. Check worker pods + `FOR UPDATE SKIP LOCKED` claim errors in logs.
3. Scale the worker HPA; inspect for a poison job (repeated claim/fail).

## webhook-dead-letters
1. Inspect `/dev/webhooks/{id}/deliveries` for the failing subscription.
2. Common cause: customer endpoint down or rejecting the HMAC signature.
3. Dead-lettered deliveries are retained; re-drive after the endpoint recovers.

## Standard operations
- Deploy: CI (`.github/workflows/ci.yml`) runs migrate + tests; K8s rollout is
  gated on green. Use `deploy/k8s/drip.yaml`.
- Migrations: `alembic upgrade head` (additive-only policy; every migration has a
  tested `downgrade`).
- Scale: workers via HorizontalPodAutoscaler (2–20); scheduler is single-leader.
