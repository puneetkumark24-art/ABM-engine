# DRIP — Service Level Objectives (Sprint 10)

SLIs are measured from the `/metrics` endpoint (request counts, latency
histogram, in-flight gauge) and the `/health/ready` DB probe.

| SLI | Definition | SLO target | Error budget |
|---|---|---|---|
| Availability | successful `/health/ready` probes / total | 99.9% monthly | 43m 12s / 30d |
| API latency (read) | p95 of GET request latency | < 300 ms | — |
| API latency (write) | p95 of POST/PATCH latency | < 500 ms | — |
| Error rate | 5xx responses / total | < 0.5% | 0.5% of requests |
| Async freshness | job queue drain lag | < 5 min p95 | — |
| Webhook delivery | delivered / (delivered + dead-lettered) | > 99% | 1% |

## Error-budget policy
When the 30-day availability budget is >50% consumed, non-critical feature
rollouts pause and reliability work is prioritized until the budget recovers.
Alerting rules in `deploy/observability/alerts.yml` fire on SLO burn.

## Measured baseline (perf harness, single-thread SQLite)
`tests/test_perf_harness.py` records read p50 ≈ 7 ms / p95 ≈ 10 ms and write
p95 ≈ 25 ms through the full middleware stack. Production (multi-worker +
Postgres) is expected to exceed these throughput numbers substantially; the
harness exists to catch order-of-magnitude regressions in CI, not to certify
production capacity — that requires the load test in the target environment
(BLOCKED-EXTERNAL: staging infra at 100k contacts / 100M events).
