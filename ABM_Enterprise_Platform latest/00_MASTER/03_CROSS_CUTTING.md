# Cross-Cutting Concerns

These apply to every module and are enforced platform-wide.

## Multi-tenancy
Every entity carries tenant_id; row-level security enforces isolation; no cross-tenant reads. Tenant provisioning, plans, suspension in Admin (25).

## AuthN / AuthZ / RBAC
OAuth2/JWT + API keys at the Gateway (23). RBAC is deny-by-default, permissions additive via roles (25). Row-level security ties records to owner/team; managers see team, admins see tenant.

## Audit logging
Every privileged mutation writes an audit entry (actor, before/after, timestamp). CRM (06) and Admin (25) own the audit stores; all engines emit.

## Event architecture
Async event bus (24) is the nervous system: at-least-once delivery, per-key ordering, idempotent consumers, schema registry + versioning, retry/DLQ/replay. Engines are decoupled producers/consumers.

## Error handling & retries
Standard error envelope (code, message, detail, trace_id). Transient failures retry with backoff; exhausted -> DLQ or failure path. Outreach failures never silently drop.

## Scheduling & workers
Central scheduler emits schedule.tick; background workers run captures, scoring, rollups, journey advancement, sends. PID/lease locks prevent double-run.

## Queue architecture
Per-domain queues (send, enrichment, ai, workflow) with priority + rate control; back-pressure via throttling.

## Caching
Redis for hot reads (scores, segments, dashboards); cache invalidation on the owning entity's change event.

## Search architecture
Postgres FTS for in-app search; cross-object search (CRM) optionally OpenSearch; pgvector for semantic/document search.

## Performance & scalability
Partition large tables (contacts, activities, events, messages); materialized views for analytics; horizontal worker scaling; 1M+ contacts and high send volume as design targets.

## Security
Secrets via vault refs (never inline); signed webhooks; PII anonymization before LLM; encryption at rest/in transit; least-privilege service accounts; PDPL compliance.

## Internationalization
English + Arabic (RTL) across UI and generated content; locale-aware timezones; KSA calendar (Sun-Thu, Ramadan blackout) enforced in sending.

## Compliance spine
Consent (none/opted_in/denied) + do_not_contact + suppression enforced at enroll AND send; HMAC-signed unsubscribe; account-centric pause; C-suite always human review; PDPL legal gate before live outreach.

## Configuration management
Per-tenant settings + feature flags in Admin; environment config via env vars; no hardcoded secrets.

## Deployment architecture
Containerized services behind API Gateway; public HTTPS ingress for inbound webhooks (email/LinkedIn/calendar); managed Postgres + Redis; blue/green deploys.

## Testing strategy
Unit + contract (OpenAPI) + integration (event flows) + property (idempotency/ordering) + load + acceptance suites per module; golden-file tests for scoring & reasoning determinism.

## Microservice boundaries
Each numbered engine is an independently deployable service (or a bounded module in a modular monolith for the 5-day build, split later). Services never share tables across boundaries; they communicate via the event bus (24) and the API Gateway (23). The CRM (06) owns the relational spine; other engines reference CRM objects by id and subscribe to CRM events. Scoring (18), Intelligence (01), and Analytics (17) are read-heavy consumers. Delivery (11), LinkedIn (12), Workflow (16) are execution services. Admin (25) + Gateway (23) + Integration Layer (24) are the platform control/plumbing plane.

## Zero Human Intervention — how it's achieved
Zero Human Intervention is achieved by the Rules Engine (15) + Workflow Engine (16) + Journey Engine (08) driving the pipeline autonomously, the AI Engine (10) generating content, and the autonomy ladder (A1-A5) governing how much runs without review — with three hard stops that always require a human: (1) C-suite outreach, (2) anything failing compliance/consent/suppression, (3) actions above the earned trust tier. The Copilot (26) is the human's window in; the platform runs without it.

## Technology stack
| Layer | Choice |
|---|---|
| Language / runtime | Python 3.12+ (async), TypeScript (front-end) |
| API framework | FastAPI + Pydantic v2 (async, OpenAPI-native) |
| ORM / migrations | SQLAlchemy 2.x + Alembic |
| Primary DB | PostgreSQL 16 — UUID PKs, JSONB, partitioning, materialized views, row-level security |
| Cache / queue / bus | Redis (cache + Streams event bus) or Kafka for scale; Celery/RQ workers |
| Search | PostgreSQL FTS + optional OpenSearch for cross-object search |
| Vector / embeddings | pgvector for semantic search + document embeddings |
| AI models | Provider-agnostic adapter (Gemini / Anthropic / OpenAI) via Integration Layer; PII anonymized |
| Email MTA | Pluggable: Mandrill-style API adapter + SMTP; native event pipeline (pixel/redirect/webhooks) |
| Front-end | React + Tailwind; visual builders for journey/workflow/email/landing |
| Auth | OAuth2 / JWT + API keys; RBAC deny-by-default; multi-tenant row-level security |
| Infra | Docker + docker-compose (dev) / Kubernetes (scale); public HTTPS ingress for webhooks |
| Observability | Structured logging, metrics, tracing, health endpoints, audit logs |
| i18n | English + Arabic (RTL), locale-aware sending & content |
