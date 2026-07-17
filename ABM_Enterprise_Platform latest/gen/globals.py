# -*- coding: utf-8 -*-
"""Global architecture content: repo tree, cross-cutting, data model, event catalog, 5-day plan."""

TITLE = "Decimal ABM Enterprise Platform"
SUBTITLE = "A self-contained, zero-external-dependency Account-Based Marketing platform — HubSpot, Mailchimp, Apollo, Customer.io, Instantly, Smartlead and n8n rebuilt as native modules."
DATE = "16 July 2026"

VISION = """The objective is Zero Human Intervention. External SaaS (HubSpot, Mailchimp, Apollo, Clay, Instantly, Smartlead, n8n) must stop being dependencies and become **native modules** the platform owns end-to-end. Instead of Signal Engine -> Clay -> Apollo -> HubSpot -> Mailchimp -> Smartlead, the flow becomes a single owned pipeline: Signal Engine -> ABM Intelligence Layer -> ABM CRM Engine (HubSpot replica) -> ABM Marketing Engine (Mailchimp replica) -> ABM Outreach Engine -> ABM Analytics Engine. This document is the complete engineering blueprint: exhaustive enough that an AI-assisted team (Claude Code / Cursor / Codex) can build it in ~5 days, with enterprise-grade quality, multi-tenancy, RBAC, Arabic/English i18n, and full extensibility."""

# The 20-folder repository structure (top level), each maps to a domain.
REPO_FOLDERS = [
 ("00_MASTER","Master architecture, global data model, event catalog, cross-cutting specs, 5-day build plan, glossary."),
 ("01_Core_Platform","Platform foundation: multi-tenancy, config, base entities, shared kernel, service/repository patterns."),
 ("02_Intelligence","Module 01 Intelligence Engine + EPIS confidence spine + reasoning streams."),
 ("03_Signal_Detection","Module 02 Signal Detection Engine (8 capture sub-streams, filter, decay)."),
 ("04_Contact_Enrichment","Module 03 Enrichment Engine + Module 04 Contact Intelligence Engine."),
 ("05_Account_Management","Module 05 Account Engine + Module 18 Lead/Account Scoring + Module 19 Pipeline."),
 ("06_CRM_Engine","Module 06 CRM Engine (full HubSpot replica)."),
 ("07_Marketing_Automation","Modules 07 Marketing, 08 Journey, 09 Campaign, 13 Landing/Forms, 14 Asset Library (Mailchimp+ replica)."),
 ("08_Email_Engine","Module 11 Email Delivery Engine (MTA, event pipeline, deliverability)."),
 ("09_LinkedIn_Engine","Module 12 LinkedIn Automation Engine (ban-risk gated)."),
 ("10_AI_Engine","Modules 10 AI Personalization + 26 AI Copilot."),
 ("11_Workflow_Engine","Module 16 Workflow Engine (n8n-style node automation)."),
 ("12_Analytics","Modules 17 Analytics + 20 Reporting + 22 Attribution."),
 ("13_Rules_Engine","Module 15 Rules Engine (no-code IF/THEN core)."),
 ("14_Admin","Modules 21 Notification + 25 Admin/User/Permission Management."),
 ("15_API","Module 23 API Gateway."),
 ("16_UI","Front-end app: dashboards, builders (journey/workflow/email/page), CRM UI, copilot; + Module 24 Integration Layer/event bus specs."),
 ("17_Database","Global schema, ER diagrams, migrations strategy, partitioning, materialized views."),
 ("18_Deployment","Docker/compose, environments, secrets, scaling, observability, backups, DR."),
 ("19_Testing","Test strategy, fixtures, contract tests, load/perf, acceptance suites."),
 ("20_Documentation","Cross-references, onboarding, runbooks, ADRs, glossary."),
]

# Per-folder standard doc set (as the user requested each folder should contain).
FOLDER_DOCSET = ["Functional Specification (FSD)","Business Requirements (BRD)","Technical Design (TDD)","Database Design & ER","API Design","Business Rules","State Machines","Sequence Diagrams","Activity Diagrams","Events","Workflows","Permissions & RBAC","Acceptance Criteria","Edge Cases","Testing","Future Enhancements"]

TECH_STACK = [
 ("Language / runtime","Python 3.12+ (async), TypeScript (front-end)"),
 ("API framework","FastAPI + Pydantic v2 (async, OpenAPI-native)"),
 ("ORM / migrations","SQLAlchemy 2.x + Alembic"),
 ("Primary DB","PostgreSQL 16 — UUID PKs, JSONB, partitioning, materialized views, row-level security"),
 ("Cache / queue / bus","Redis (cache + Streams event bus) or Kafka for scale; Celery/RQ workers"),
 ("Search","PostgreSQL FTS + optional OpenSearch for cross-object search"),
 ("Vector / embeddings","pgvector for semantic search + document embeddings"),
 ("AI models","Provider-agnostic adapter (Gemini / Anthropic / OpenAI) via Integration Layer; PII anonymized"),
 ("Email MTA","Pluggable: Mandrill-style API adapter + SMTP; native event pipeline (pixel/redirect/webhooks)"),
 ("Front-end","React + Tailwind; visual builders for journey/workflow/email/landing"),
 ("Auth","OAuth2 / JWT + API keys; RBAC deny-by-default; multi-tenant row-level security"),
 ("Infra","Docker + docker-compose (dev) / Kubernetes (scale); public HTTPS ingress for webhooks"),
 ("Observability","Structured logging, metrics, tracing, health endpoints, audit logs"),
 ("i18n","English + Arabic (RTL), locale-aware sending & content"),
]

# Cross-cutting concerns, each a spec section.
CROSS_CUTTING = [
 ("Multi-tenancy","Every entity carries tenant_id; row-level security enforces isolation; no cross-tenant reads. Tenant provisioning, plans, suspension in Admin (25)."),
 ("AuthN / AuthZ / RBAC","OAuth2/JWT + API keys at the Gateway (23). RBAC is deny-by-default, permissions additive via roles (25). Row-level security ties records to owner/team; managers see team, admins see tenant."),
 ("Audit logging","Every privileged mutation writes an audit entry (actor, before/after, timestamp). CRM (06) and Admin (25) own the audit stores; all engines emit."),
 ("Event architecture","Async event bus (24) is the nervous system: at-least-once delivery, per-key ordering, idempotent consumers, schema registry + versioning, retry/DLQ/replay. Engines are decoupled producers/consumers."),
 ("Error handling & retries","Standard error envelope (code, message, detail, trace_id). Transient failures retry with backoff; exhausted -> DLQ or failure path. Outreach failures never silently drop."),
 ("Scheduling & workers","Central scheduler emits schedule.tick; background workers run captures, scoring, rollups, journey advancement, sends. PID/lease locks prevent double-run."),
 ("Queue architecture","Per-domain queues (send, enrichment, ai, workflow) with priority + rate control; back-pressure via throttling."),
 ("Caching","Redis for hot reads (scores, segments, dashboards); cache invalidation on the owning entity's change event."),
 ("Search architecture","Postgres FTS for in-app search; cross-object search (CRM) optionally OpenSearch; pgvector for semantic/document search."),
 ("Performance & scalability","Partition large tables (contacts, activities, events, messages); materialized views for analytics; horizontal worker scaling; 1M+ contacts and high send volume as design targets."),
 ("Security","Secrets via vault refs (never inline); signed webhooks; PII anonymization before LLM; encryption at rest/in transit; least-privilege service accounts; PDPL compliance."),
 ("Internationalization","English + Arabic (RTL) across UI and generated content; locale-aware timezones; KSA calendar (Sun-Thu, Ramadan blackout) enforced in sending."),
 ("Compliance spine","Consent (none/opted_in/denied) + do_not_contact + suppression enforced at enroll AND send; HMAC-signed unsubscribe; account-centric pause; C-suite always human review; PDPL legal gate before live outreach."),
 ("Configuration management","Per-tenant settings + feature flags in Admin; environment config via env vars; no hardcoded secrets."),
 ("Deployment architecture","Containerized services behind API Gateway; public HTTPS ingress for inbound webhooks (email/LinkedIn/calendar); managed Postgres + Redis; blue/green deploys."),
 ("Testing strategy","Unit + contract (OpenAPI) + integration (event flows) + property (idempotency/ordering) + load + acceptance suites per module; golden-file tests for scoring & reasoning determinism."),
]

# Global/shared data-model entities (the shared kernel every module references).
GLOBAL_ENTITIES = [
 ("tenant","Workspace/org — root of multi-tenancy.","Admin (25)"),
 ("user / team / role","Identity + RBAC.","Admin (25)"),
 ("account","Target organization (bank/fintech/subsidiary/vendor).","Account Engine (05)"),
 ("contact","Person at an account.","Contact Engine (04)"),
 ("company","Non-target org / vendor / partner.","CRM (06)"),
 ("relationship","Graph edge (org/person/vendor/tech).","CRM (06) / Graph"),
 ("signal / raw_capture","Captured intelligence + provenance.","Signal Engine (02)"),
 ("intelligence_record / nba / hypothesis","Reasoned intelligence.","Intelligence (01)"),
 ("deal / pipeline / stage","Revenue objects.","CRM (06) / Pipeline (19)"),
 ("activity","Universal interaction record.","CRM (06)"),
 ("campaign / journey / enrollment","Orchestration objects.","Campaign (09)/Journey (08)"),
 ("email_campaign / message / delivery_event","Marketing + delivery.","Marketing (07)/Delivery (11)"),
 ("account_score / lead_score / modifier","Scoring.","Scoring (18)"),
 ("event","Platform event (bus).","Integration Layer (24)"),
 ("audit_log","Change history.","CRM (06)/Admin (25)"),
]

# Master event catalog (representative — the bus contract).
EVENT_CATALOG = [
 ("signal.created","Signal Engine","Intelligence, Scoring, Account, Enrichment"),
 ("signal.cluster.promoted","Signal Engine","Intelligence"),
 ("intelligence.record.created","Intelligence","Scoring, CRM, Copilot"),
 ("intelligence.nba.created","Intelligence","CRM, Notification, Copilot"),
 ("enrichment.entity.updated","Enrichment","Contact, Account, CRM, Scoring"),
 ("contact.consent.changed","Contact","Marketing, Journey, Delivery"),
 ("account.tiered","Account","Enrichment, Journey, Notification"),
 ("account.held","Account","Journey, LinkedIn, Marketing (pause cascade)"),
 ("score.updated / score.threshold.crossed","Scoring","Account, Intelligence, Analytics, Notification"),
 ("deal.stage.changed","CRM/Pipeline","Pipeline, Attribution, Analytics, Marketing (transactional)"),
 ("email.campaign.sent","Marketing","Delivery, Analytics"),
 ("email.event.opened/clicked/bounced/complained","Delivery","Marketing, Contact, Scoring, Attribution, Analytics"),
 ("email.reply.received","Delivery","Account (pause), Journey (pause), Notification"),
 ("journey.enrolled / step.executed / goal.met / exited","Journey","Analytics, Campaign, Attribution"),
 ("linkedin.reply.received / seat.cooldown / circuit_breaker.tripped","LinkedIn","Account, Journey, Notification"),
 ("form.submitted / consent.captured","Landing/Forms","Contact, Journey, Analytics"),
 ("rule.fired","Rules","Audit, target engines"),
 ("workflow.run.finished / approval.requested","Workflow","Notification, Analytics"),
 ("meeting.booked","Calendar/CRM","Account, Pipeline, Scoring, Attribution, Notification"),
 ("quota.exhausted","Admin","Notification, calling engine (block)"),
]

# The 5-day AI-assisted build plan.
BUILD_PLAN = [
 ("Day 1 — Foundation","Core Platform (01): multi-tenancy, base entities, shared kernel, config, RBAC scaffolding. Database (17): global schema + migrations. Integration Layer (24): event bus + schema registry. API Gateway (23) skeleton. Admin (25) tenants/users/roles. Outcome: a multi-tenant, event-driven skeleton with auth."),
 ("Day 2 — Data & Intelligence","Signal Engine (02): raw_capture, SIG-NEWS worker, filter, decay. Enrichment (03) waterfall + verify. Contact (04) + Account (05) + Scoring (18): the account-first model + 0-100 score + Effective-Opportunity. Intelligence (01) + EPIS + reasoning streams. Outcome: signals flow to scored, tiered accounts with briefs."),
 ("Day 3 — CRM & Marketing replicas","CRM Engine (06): objects, properties, deals, activities, committee, graph, views, merge, audit, timeline. Marketing (07) + Journey (08) + Campaign (09): audiences, templates, campaigns, journeys. Email Delivery (11): send + event pipeline. Outcome: HubSpot + Mailchimp replicas operational end-to-end."),
 ("Day 4 — Automation & AI","Rules Engine (15): no-code IF/THEN. Workflow Engine (16): node automation. AI Personalization (10): 7-agent chain + QC. Landing/Forms (13) + Assets (14). LinkedIn (12) behind circuit breaker. Notification (21). Outcome: autonomous orchestration with AI content + compliance gates."),
 ("Day 5 — Insight, Copilot, Hardening","Analytics (17) + Attribution (22) + Reporting (20) + exec briefs. AI Copilot (26). Pipeline (19) forecasting. Cross-cutting hardening: RBAC matrix, quotas, i18n, KSA calendar, load tests, acceptance suites. Outcome: full platform with copilot, analytics, and the feedback loop closed."),
]

MICROSERVICE_BOUNDARIES = """Each numbered engine is an independently deployable service (or a bounded module in a modular monolith for the 5-day build, split later). Services never share tables across boundaries; they communicate via the event bus (24) and the API Gateway (23). The CRM (06) owns the relational spine; other engines reference CRM objects by id and subscribe to CRM events. Scoring (18), Intelligence (01), and Analytics (17) are read-heavy consumers. Delivery (11), LinkedIn (12), Workflow (16) are execution services. Admin (25) + Gateway (23) + Integration Layer (24) are the platform control/plumbing plane."""

ZERO_HUMAN = """Zero Human Intervention is achieved by the Rules Engine (15) + Workflow Engine (16) + Journey Engine (08) driving the pipeline autonomously, the AI Engine (10) generating content, and the autonomy ladder (A1-A5) governing how much runs without review — with three hard stops that always require a human: (1) C-suite outreach, (2) anything failing compliance/consent/suppression, (3) actions above the earned trust tier. The Copilot (26) is the human's window in; the platform runs without it."""
