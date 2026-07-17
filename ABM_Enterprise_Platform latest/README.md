# Decimal ABM Enterprise Platform

_A self-contained, zero-external-dependency Account-Based Marketing platform — HubSpot, Mailchimp, Apollo, Customer.io, Instantly, Smartlead and n8n rebuilt as native modules._

**Compiled:** 16 July 2026

## Vision — Zero Human Intervention

The objective is Zero Human Intervention. External SaaS (HubSpot, Mailchimp, Apollo, Clay, Instantly, Smartlead, n8n) must stop being dependencies and become **native modules** the platform owns end-to-end. Instead of Signal Engine -> Clay -> Apollo -> HubSpot -> Mailchimp -> Smartlead, the flow becomes a single owned pipeline: Signal Engine -> ABM Intelligence Layer -> ABM CRM Engine (HubSpot replica) -> ABM Marketing Engine (Mailchimp replica) -> ABM Outreach Engine -> ABM Analytics Engine. This document is the complete engineering blueprint: exhaustive enough that an AI-assisted team (Claude Code / Cursor / Codex) can build it in ~5 days, with enterprise-grade quality, multi-tenancy, RBAC, Arabic/English i18n, and full extensibility.


## The pipeline (owned end-to-end)
```
Signal Engine
  -> ABM Intelligence Layer
  -> ABM CRM Engine (HubSpot replica)
  -> ABM Marketing Engine (Mailchimp replica)
  -> ABM Outreach Engine (Email + LinkedIn)
  -> ABM Analytics Engine
  (Rules + Workflow + AI orchestrate; Copilot = the human's window)
```

## The 26 modules
| # | Module | Domain folder | Replaces |
|---|---|---|---|
| 01 | Intelligence Engine | `02_Intelligence` | The 'brain' |
| 02 | Signal Detection Engine | `03_Signal_Detection` | 6sense/Bombora intent + Google Alerts + custom scrapers |
| 03 | Contact & Account Enrichment Engine | `04_Contact_Enrichment` | Apollo + Clay + ZoomInfo + Lusha |
| 04 | Contact Intelligence Engine | `04_Contact_Enrichment` | HubSpot Contacts + Apollo person records |
| 05 | Account Engine | `05_Account_Management` | HubSpot Companies + 6sense account model |
| 06 | CRM Engine (HubSpot Replica) | `06_CRM_Engine` | HubSpot CRM in full |
| 07 | Marketing Automation Engine (Mailchimp Replica) | `07_Marketing_Automation` | Mailchimp + Customer.io + Brevo |
| 08 | Journey Builder Engine | `07_Marketing_Automation` | HubSpot Workflows + Customer.io journeys |
| 09 | Campaign Builder Engine | `07_Marketing_Automation` | HubSpot Campaigns + orchestration wrapper over ABM plays. |
| 10 | AI Personalization Engine | `10_AI_Engine` | Jasper/Copy.ai/Clay AI columns + custom prompt stacks |
| 11 | Email Delivery Engine | `08_Email_Engine` | Mandrill/SendGrid MTA + Postfix |
| 12 | LinkedIn Automation Engine | `09_LinkedIn_Engine` | Smartlead/Expandi/Dux-Soup |
| 13 | Landing Page & Forms Engine | `07_Marketing_Automation` | HubSpot Landing Pages + Forms + Unbounce + popups/preference |
| 14 | Asset Library | `07_Marketing_Automation` | HubSpot Files + DAM |
| 15 | Rules Engine | `13_Rules_Engine` | HubSpot workflow logic + custom IFTTT |
| 16 | Workflow Engine (n8n-style) | `11_Workflow_Engine` | n8n / Zapier / Make |
| 17 | Analytics Engine | `12_Analytics` | HubSpot Analytics + Mailchimp Reports + product analytics |
| 18 | Lead & Account Scoring Engine | `05_Account_Management` | HubSpot scoring + 6sense/MadKudu |
| 19 | Pipeline Management Engine | `05_Account_Management` | HubSpot deal pipelines + forecasting. |
| 20 | Reporting Engine | `12_Analytics` | HubSpot reports/dashboards + exports + scheduled digests. |
| 21 | Notification Engine | `14_Admin` | HubSpot notifications + Slack/Teams alerts. |
| 22 | Attribution Engine | `12_Analytics` | HubSpot attribution + Bizible-style multi-touch models. |
| 23 | API Gateway | `15_API` | Kong/Apigee + HubSpot public API surface. |
| 24 | Integration Layer & Event Bus | `16_UI` | Internal Kafka/Redis event bus + connector framework (option |
| 25 | Admin Console & User/Permission Management | `14_Admin` | HubSpot settings + super-admin + billing/quotas + RBAC. |
| 26 | AI Copilot | `10_AI_Engine` | HubSpot ChatSpot / Breeze |

## Repository structure

- **`00_MASTER/`** — Master architecture, global data model, event catalog, cross-cutting specs, 5-day build plan, glossary.
- **`01_Core_Platform/`** — Platform foundation: multi-tenancy, config, base entities, shared kernel, service/repository patterns.
- **`02_Intelligence/`** — Module 01 Intelligence Engine + EPIS confidence spine + reasoning streams.
- **`03_Signal_Detection/`** — Module 02 Signal Detection Engine (8 capture sub-streams, filter, decay).
- **`04_Contact_Enrichment/`** — Module 03 Enrichment Engine + Module 04 Contact Intelligence Engine.
- **`05_Account_Management/`** — Module 05 Account Engine + Module 18 Lead/Account Scoring + Module 19 Pipeline.
- **`06_CRM_Engine/`** — Module 06 CRM Engine (full HubSpot replica).
- **`07_Marketing_Automation/`** — Modules 07 Marketing, 08 Journey, 09 Campaign, 13 Landing/Forms, 14 Asset Library (Mailchimp+ replica).
- **`08_Email_Engine/`** — Module 11 Email Delivery Engine (MTA, event pipeline, deliverability).
- **`09_LinkedIn_Engine/`** — Module 12 LinkedIn Automation Engine (ban-risk gated).
- **`10_AI_Engine/`** — Modules 10 AI Personalization + 26 AI Copilot.
- **`11_Workflow_Engine/`** — Module 16 Workflow Engine (n8n-style node automation).
- **`12_Analytics/`** — Modules 17 Analytics + 20 Reporting + 22 Attribution.
- **`13_Rules_Engine/`** — Module 15 Rules Engine (no-code IF/THEN core).
- **`14_Admin/`** — Modules 21 Notification + 25 Admin/User/Permission Management.
- **`15_API/`** — Module 23 API Gateway.
- **`16_UI/`** — Front-end app: dashboards, builders (journey/workflow/email/page), CRM UI, copilot; + Module 24 Integration Layer/event bus specs.
- **`17_Database/`** — Global schema, ER diagrams, migrations strategy, partitioning, materialized views.
- **`18_Deployment/`** — Docker/compose, environments, secrets, scaling, observability, backups, DR.
- **`19_Testing/`** — Test strategy, fixtures, contract tests, load/perf, acceptance suites.
- **`20_Documentation/`** — Cross-references, onboarding, runbooks, ADRs, glossary.

## How to read this repo
Start here (00_MASTER), then each domain folder holds its module specs. Every module `.md` follows the same 18-section template (purpose → scope → personas → entities → APIs → workflows → state machine → events → rules → RBAC → validations → errors → integrations → testing → acceptance → edge cases → checklist → future).

## Build it in 5 days
See `00_MASTER/05_BUILD_PLAN.md`.
