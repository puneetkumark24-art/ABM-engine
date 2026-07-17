# 5-Day AI-Assisted Build Plan

Assumes Claude Code / Cursor / Codex building against these specs. Each day ends with a working, testable slice.

## Day 1 — Foundation
Core Platform (01): multi-tenancy, base entities, shared kernel, config, RBAC scaffolding. Database (17): global schema + migrations. Integration Layer (24): event bus + schema registry. API Gateway (23) skeleton. Admin (25) tenants/users/roles. Outcome: a multi-tenant, event-driven skeleton with auth.

## Day 2 — Data & Intelligence
Signal Engine (02): raw_capture, SIG-NEWS worker, filter, decay. Enrichment (03) waterfall + verify. Contact (04) + Account (05) + Scoring (18): the account-first model + 0-100 score + Effective-Opportunity. Intelligence (01) + EPIS + reasoning streams. Outcome: signals flow to scored, tiered accounts with briefs.

## Day 3 — CRM & Marketing replicas
CRM Engine (06): objects, properties, deals, activities, committee, graph, views, merge, audit, timeline. Marketing (07) + Journey (08) + Campaign (09): audiences, templates, campaigns, journeys. Email Delivery (11): send + event pipeline. Outcome: HubSpot + Mailchimp replicas operational end-to-end.

## Day 4 — Automation & AI
Rules Engine (15): no-code IF/THEN. Workflow Engine (16): node automation. AI Personalization (10): 7-agent chain + QC. Landing/Forms (13) + Assets (14). LinkedIn (12) behind circuit breaker. Notification (21). Outcome: autonomous orchestration with AI content + compliance gates.

## Day 5 — Insight, Copilot, Hardening
Analytics (17) + Attribution (22) + Reporting (20) + exec briefs. AI Copilot (26). Pipeline (19) forecasting. Cross-cutting hardening: RBAC matrix, quotas, i18n, KSA calendar, load tests, acceptance suites. Outcome: full platform with copilot, analytics, and the feedback loop closed.

## Guardrails during the build
- Never delete production data; always generate migrations.
- Inspect before modifying; reuse existing ABM Engine + DRIP code.
- Compliance gates (consent/suppression/hold/C-suite) are non-negotiable and built in from Day 1.
- Every module ships with its acceptance suite from its spec.
