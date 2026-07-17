# Transformation Backlog (seeded from the Independent Audit)

Fields: ID · Module · Description · BizValue · TechValue · Deps · Risk · Effort ·
Priority · Status · Target Release · Score Δ. Status ∈ {TODO, IN-PROGRESS, DONE,
BLOCKED-EXTERNAL}. Effort in ideal-eng-weeks (team estimate).

## Sprint 1 — Enterprise Platform Foundation
| ID | Description | Biz | Tech | Deps | Risk | Effort | Pri | Status | Rel | Δ |
|---|---|---|---|---|---|---|---|---|---|---|
| S1-01 | Route-level authorization (wire require_scope/tenant_db into every router) | H | H | auth.py | M | 1 | P0 | **DONE** | S1 | authz 2→6 |
| S1-02 | Observability: structured JSON logs + request-id + /health/live+ready + /metrics (Prometheus) | H | H | — | M | 1.5 | P0 | **DONE** | S1 | monitoring 0→5, logging 2→5, obs 0→5 |
| S1-03 | Universal audit: SQLAlchemy event → before/after audit_events (append-only, per-tenant) | H | H | models | M | 1 | P0 | **DONE** | S1 | audit 3→6 |
| S1-04 | CI/CD pipeline (GitHub Actions: lint + migrate + test-matrix on PG) | H | H | tests | L | 0.5 | P0 | **DONE** | S1 | ci/cd 0→6 |
| S1-05 | Kubernetes manifests + Terraform skeleton (api/worker/scheduler/pg/redis, HPA, secrets) | H | H | deploy | M | 2 | P0 | **DONE** | S1 | deploy 3→6 |
| S1-06 | Config/secrets abstraction (env + vault-ready interface) | M | H | — | L | 0.5 | P1 | **DONE** | S1 | security +, config + |
| S1-07 | Strict RLS (WITH CHECK) + per-tenant unique constraints | H | H | S1-01 | M | 1 | P1 | TODO | S1 | multitenancy 7→8 |
| S1-08 | OIDC/SSO + MFA + SCIM integration | H | H | S1-01 | H | 4 | P0 | BLOCKED-EXTERNAL (IdP tenant) | S1/S9 | security + |
| S1-09 | Backup automation + PITR + DR runbook | H | M | infra | M | 2 | P0 | BLOCKED-EXTERNAL (managed PG) | S1/S10 | DR 0→ |
| S1-10 | Kafka/Redpanda bus + Temporal (throughput/HA) | M | H | infra | H | 4 | P1 | TODO | S6/S10 | scalability + |

## Sprint 2 — CRM (selected)
| ID | Description | Pri | Effort | Status | Δ target |
|---|---|---|---|---|---|
| S2-01 | Custom objects framework (dynamic object types, not just properties) | P0 | 3 | TODO | CRM +8 |
| S2-02 | Money type (amount_minor+currency) replacing free-text | P0 | 0.5 | TODO | DB + |
| S2-03 | Property history / SCD-2 on person/org/deal | P1 | 2 | TODO | CRM + |
| S2-04 | Meetings/scheduler; quotes/products/price-books; calling/inbox | P1 | 6 | TODO | CRM + |
| S2-05 | CRM UI (records, board, timeline, dashboards) | P0 | 12+ | TODO | CRM ++ |

## Sprint 3 — Marketing (selected)
| ID | Description | Pri | Effort | Status | Δ target |
|---|---|---|---|---|---|
| S3-01 | Real email transport (SES) + IP warmup automation + feedback loops | P0 | 3 | BLOCKED-EXTERNAL (domain/creds) | Email ++ |
| S3-02 | Drag-drop email/page/journey builders (UI) | P0 | 12+ | TODO | Mktg ++ |
| S3-03 | Multivariate testing + dynamic content blocks | P1 | 2 | TODO | Mktg + |

## Sprint 4 — ABM Intelligence (selected)
| ID | Description | Pri | Effort | Status | Δ target |
|---|---|---|---|---|---|
| S4-01 | Buying-committee inference engine (title→role, org-chart, coverage) | P0 | 3 | TODO | BuyingCommittee ++ |
| S4-02 | 8 signal collectors (SAMA/news/exec/vendor/…) + content-hash dedup | P0 | 5 | TODO | Signal ++ |
| S4-03 | Real enrichment providers (Apollo/Clay) | P0 | 2 | BLOCKED-EXTERNAL (data contract) | ABM ++ |
| S4-04 | Intent data (6sense/bidstream) | P1 | — | BLOCKED-EXTERNAL (data network) | ABM + |

## Sprints 5–10 (headline items)
| ID | Description | Sprint | Pri | Status |
|---|---|---|---|---|
| S6-01 | Visual workflow builder + Temporal durable execution | S6 | P0 | TODO |
| S7-01 | Analytics warehouse (ClickHouse/Timescale) + BI + real-time dashboards | S7 | P0 | TODO |
| S8-01 | Public API + GraphQL + SDKs + OAuth apps + marketplace + dev portal | S8 | P1 | TODO |
| S9-01 | SOC2/ISO27001/PDPL certification + pen-test + threat model formalization | S9 | P0 | BLOCKED-EXTERNAL (auditors) |
| S10-01 | Load/chaos/perf testing at 100k contacts / 100M events; capacity plan | S10 | P0 | TODO |

## Legend on external blockers
`BLOCKED-EXTERNAL` = code integration point + spec delivered; final credit needs
a business-supplied credential, data contract, infra, or external audit. These
are the honest ceiling on how far pure engineering moves the score.
