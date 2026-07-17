# Transformation Constitution — the single governing document

This is the constitution for transforming the DRIP / ABM platform from its
audited maturity (**34/100**, see `INDEPENDENT_AUDIT_REPORT.md`) into a
production-grade enterprise SaaS platform. It is not executed in one pass; it
governs a 10-sprint program (`SPRINTS.md`) tracked in `BACKLOG.md`.

## Mission
Do NOT rebuild the ABM. Eliminate every weakness the audit identified until the
platform is deployable inside Tier-1 banks. Target scale: 500+ orgs, 100k+
contacts, millions of edges, hundreds of millions of events, thousands of
concurrent workflows and users, enterprise security, multi-tenancy, HA, zero
human intervention, Arabic + English.

## Engineering philosophy — KEEP · IMPROVE · EXTEND · HARDEN
Everything implemented is an investment. Preserve it wherever technically
feasible. Only REPLACE when incremental evolution is provably impossible, and
then only with written engineering proof. Prefer additive migrations; avoid
breaking APIs; maintain backward compatibility.

## The audit is the baseline (single source of truth)
- **Protect the strengths** the audit credited: multi-tenant RLS (proven),
  partitioned event tables (proven), durable async worker loop (proven), the
  autonomous decision + compliance layer, and the 275-check test suite.
- **Systematically eliminate every weakness** it listed.
- **Design and integrate** every missing enterprise capability — not as
  recommendations, but as built, tested code + complete specs.

## Definition of Done (per module — the Completeness Rule)
A module is complete only when ALL are true: Business design · Functional design
· Technical design · Database · API · Security · Observability · DevOps ·
Deployment · Testing · Documentation · Migration · Operational runbook ·
Admin guide · Developer guide · Production checklist. If any is missing, keep
going.

## Transformation framework (per module)
1. **Current-state assessment** (impl, strengths, weaknesses, tech debt, perf/
   security/scale/ops limits, missing enterprise capabilities).
2. **Enterprise benchmark** vs. HubSpot Enterprise, Salesforce, Mailchimp,
   Customer.io, Clay, Apollo, Outreach, Salesloft, Demandbase, 6sense, n8n —
   per feature: current / enterprise / gap / business impact / technical impact
   / priority / complexity.
3. **Transformation decision** — exactly one of KEEP · MINOR IMPROVEMENT ·
   MAJOR ENHANCEMENT · PARTIAL REFACTOR · FULL REPLACEMENT, with justification.
4. **Design everything** required for production (BRD/PRD/FSD/TDD/HLD/LLD/DB/ER/
   state machines/sequence/component/deployment diagrams/APIs/validation/rules/
   permissions/audit/cache/queue/worker/search/observability/DR/backup/security/
   threat model/OWASP/encryption/RBAC/ABAC/SSO/SCIM/MFA/CI-CD/K8s/Terraform/
   testing/i18n/migration/rollback/docs).
5. **Integrate into the current repo** — current DB, APIs, workers, queues,
   events, security, AI, CRM, workflow, marketing. Never design in isolation.
6. **Re-score** — previous → new, reason, remaining weaknesses. Update backlog.

## Master success criteria (project complete only when ALL ≥ 95/100)
Overall · Architecture · CRM · Marketing Automation · Workflow Engine · AI
Platform · Signal Intelligence · Buying-Committee Intelligence · Database ·
Security · Scalability · Enterprise Readiness · Production Readiness ·
Documentation.

## Final rule
Behave like the engineering leadership team delivering a production platform over
multiple releases — not a consultant writing recommendations. Every output moves
the repository from audited maturity toward a deployable enterprise-grade
AI-native ABM operating system.

## Honesty clause (added by the engineering lead)
Some 95/100 targets depend on non-code inputs — real deploy infrastructure,
domain/IP warmup for sending, purchased enrichment/intent data, SSO tenant
config, and external SOC2/ISO/PDPL certification. For those, the program
delivers the *complete, tested integration point and specification*; the final
credit is earned when the business supplies the credential/contract/audit. The
backlog marks these `BLOCKED-EXTERNAL` so they are never silently claimed as
done.
