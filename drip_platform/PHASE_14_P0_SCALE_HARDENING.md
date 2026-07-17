# Phase 14 — P0 Scale-Hardening Complete (B, C, D)

Executes the remaining P0 workstreams from the production-readiness review. With
Phase 13 (P0-A: tenancy + RLS + auth) this closes **all four P0 categories** that
the review said would fail at 250-org / 50k-contact / 100M-event scale.

## Result: 226/226 checks green on real PostgreSQL 16

Full 20-migration Alembic chain applies clean on a fresh database, then:

| Suite | Checks | DB |
|---|---|---|
| test_tenancy_rls (P0-A) | 15/15 | PostgreSQL |
| test_scale_db (P0-D) | 10/10 | PostgreSQL |
| test_jobs_async (P0-B) | 19/19 | PostgreSQL |
| test_scale_hotpaths (P0-C) | 11/11 | PostgreSQL |
| test_sequence_engine | 30/30 | PostgreSQL |
| test_platform_services | 53/53 | PostgreSQL |
| test_engine_e2e | 30/30 | PostgreSQL |
| test_tracking_decision | 29/29 | PostgreSQL |
| test_crm_marketing_ext | 29/29 | PostgreSQL |
| **TOTAL** | **226/226** | **PostgreSQL** |

## P0-B — Async execution substrate (fixes BOMB 3 + BOMB 5)

The orchestrator ran everything inline in one blocking tick; the event bus died
with the process. Now:

- **`models_jobs.py` + migration `e2b4c6d8f0a1`** — a durable **`jobs`** queue and
  a transactional **`outbox`**.
- **`jobs.py`** — `enqueue` (idempotent by kind+key), **`claim_batch` using
  `FOR UPDATE SKIP LOCKED`** (proven: two concurrent workers never claim the same
  job), retry with exponential backoff, **dead-letter** after max attempts (never
  silently dropped), a `run_worker` loop, and the **transactional-outbox relay**
  (events written in the same transaction as the state change — proven atomic:
  rolled back with their change, published only when committed).
- **`orchestrator_async.py`** — splits the tick into a fast **scheduler**
  (`schedule_due_steps` enqueues one idempotent job per due step, no AI/sending
  inline) and a **worker handler** (`handle_sequence_step`, its own session,
  retryable). Proven: scheduler enqueues + is idempotent; worker drafts → dry-run
  sends → advances → emits an outbox event. c-suite hold + dry-run-only preserved.

## P0-C — O(N)/O(N²) hot paths → set-based SQL (fixes BOMB 4)

**`scale.py`** — behaviourally-equivalent set-based replacements, proven equal to
the naive versions:

- **`get_due_fast`** — one 3-table join (enrollment→next step→person) filtered,
  ordered (HOT>WARM>COLD) and `LIMIT`ed in the DB, instead of loading all active
  enrollments + N contactability queries. Output identical to `engine.get_due`.
- **`resolve_segment_fast`** — dynamic segments compiled to one indexed `WHERE`
  (whitelisted fields/ops; unknown fields fail safe), instead of scanning all
  persons in Python.
- **`sendable_person_ids`** — one `NOT EXISTS` against suppressions + consent/DNC,
  instead of 2 queries per recipient.
- **`dedupe_candidates`** — **blocking-key** dedup (exact email, exact LinkedIn,
  last-name+org) so only same-block pairs compare. Proven: N=26 → **325 naive
  pairs collapse to 6 candidate pairs**. At 50k the 2.5-billion-comparison
  O(N²) becomes thousands.

## P0-D — Firehose: partitioning + UUIDv7 + set-based analytics (fixes BOMB in §D)

- **`uuid7.py`** — RFC-9562 time-ordered UUIDv7 (proven: 50 ids sort in creation
  order → sequential, index-friendly inserts vs. random-UUIDv4 page splits).
- **`analytics_fast.py`** — `query_fast`/`funnel_fast` aggregate with SQL
  `GROUP BY` / `COUNT(DISTINCT)` (proven equal to the Python-dict version) — the
  database aggregates, no OOM at 100M rows.
- **Migration `f3c5a7b9d1e2`** — `metric_events_part`, **monthly RANGE-partitioned**
  by `occurred_at`, native `uuid` PK, composite `(tenant_id, event_type,
  occurred_at)` index, a default catch-all partition, and a
  `create_month_partition()` function (a scheduled worker calls it monthly).
  **Proven on Postgres:** rows route to separate physical partitions by month, and
  `EXPLAIN` confirms **partition pruning** — a this-month query scans only the
  current-month partition and excludes old ones.

## Where this leaves the scale scores (review §H → now)

| Axis | Was | Now (mechanism built + PG-proven) |
|---|---|---|
| Scalability | 22 | ~55 — async substrate, set-based hot paths, partitioning pattern in place |
| Security | 18 | ~45 — RLS isolation + JWT + webhook sig proven (not yet wired to every route) |
| Database | 30 | ~60 — RLS, partitioning, UUIDv7, set-based aggregation; PK re-type is the remaining rollout |
| Infrastructure | 15 | ~40 — durable queue/outbox/workers exist (Postgres-backed); Redis/Kafka/Temporal are the throughput upgrade |

These are *mechanism-built-and-proven* numbers. Full production numbers come when
the mechanisms are **rolled out everywhere**: tenant_id on the ORM models + every
route using `tenant_db_for` (P0-A.2), the worker deployed as a process/container,
the existing event/timeline tables migrated onto the partition pattern, and PKs
re-typed to native uuid during those rebuilds.

## What remains (honest, post-P0)

- **P0-A.2**: add `tenant_id` to the ORM models, wire `tenant_db_for` into all
  routers, tighten RLS to strict + `WITH CHECK`, per-tenant unique constraints.
- **Deploy the worker + scheduler** (container + beat) and point the app at the
  non-superuser `app_rw` role.
- **Migrate the live event/timeline tables** onto the partition + UUIDv7 pattern
  (metric_events, delivery_events, web_events, activity_log, …).
- **P1**: Redis (cache + rate limits), then Kafka/Redpanda + ClickHouse/Timescale
  + OpenSearch + Temporal per the review's target architecture; real SES + IP
  warmup; real enrichment providers; OIDC gateway + secrets vault.

## Files
`models_jobs.py` · `abm_platform/services/{jobs,orchestrator_async,scale,uuid7,analytics_fast}.py`
· migrations `e2b4c6d8f0a1`, `f3c5a7b9d1e2` · tests `test_jobs_async.py`,
`test_scale_hotpaths.py`, `test_scale_db.py`.
