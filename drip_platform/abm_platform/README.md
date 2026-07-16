# platform/ — 26-Module Enterprise Structure (inside drip_platform)

The full ABM Enterprise Platform (blueprint: `ABM_Enterprise_Platform/`) mapped
onto this codebase, **additively**. `drip_platform/` remains the single engine
(per MASTER_CONSOLIDATION_PLAN); this package organizes all 26 modules and wires
the already-built ones to their real code.

## Status: 4 LIVE · 6 PARTIAL · 16 SCAFFOLD  (of 26)

### LIVE (working code)
- **02 Signal Detection Engine** — `LIVE` → wired to `etl.signal_decay, etl.signal_intel, models.Signal`
- **08 Journey / Sequence Engine** — `LIVE` → wired to `sequences.engine, sequences.send_window`
- **18 Lead & Account Scoring Engine** — `LIVE` → wired to `scoring, models.AccountScore, modifiers.json`
- **24 Integration Layer & Event Bus** — `LIVE` → wired to `abm_platform.events`

### PARTIAL (real code, incomplete vs. blueprint)
- **01 Intelligence Engine** — `PARTIAL` → wired to `scoring, etl.signal_intel`
- **04 Contact Intelligence Engine** — `PARTIAL` → wired to `models.Person, routers.persons`
- **05 Account Engine** — `PARTIAL` → wired to `models.Organization, models.AccountIntelligence, routers.organizations`
- **06 CRM Engine (HubSpot Replica)** — `PARTIAL` → wired to `models(Organization,Person,Opportunity,BuyingCommitteeMember,ActivityLog,AuditLog)`
- **19 Pipeline Management Engine** — `PARTIAL` → wired to `models.Opportunity, routers.opportunities`
- **23 API Gateway** — `PARTIAL` → wired to `main.app (FastAPI surface)`

### SCAFFOLD (structure + spec, not yet implemented)
- **03 Contact & Account Enrichment Engine** — `SCAFFOLD`
- **07 Marketing Automation Engine (Mailchimp Replica)** — `SCAFFOLD` → wired to `models.Template, models.Draft`
- **09 Campaign Builder Engine** — `SCAFFOLD`
- **10 AI Personalization Engine** — `SCAFFOLD` → wired to `models.Draft`
- **11 Email Delivery Engine** — `SCAFFOLD` → wired to `models.Unsubscribe`
- **12 LinkedIn Automation Engine** — `SCAFFOLD` → wired to `models.OutreachChannel`
- **13 Landing Page & Forms Engine** — `SCAFFOLD`
- **14 Asset Library** — `SCAFFOLD` → wired to `models.DocumentUpload`
- **15 Rules Engine** — `SCAFFOLD`
- **16 Workflow Engine (n8n-style)** — `SCAFFOLD`
- **17 Analytics Engine** — `SCAFFOLD`
- **20 Reporting Engine** — `SCAFFOLD`
- **21 Notification Engine** — `SCAFFOLD`
- **22 Attribution Engine** — `SCAFFOLD`
- **25 Admin Console & User/Permission Mgmt** — `SCAFFOLD` → wired to `models.AuditLog`
- **26 AI Copilot** — `SCAFFOLD`

## Layout
```
platform/
  __init__.py        imports registry + events (side-effect free)
  events.py          Module 24 — in-process event bus (LIVE, self-tested)
  registry.py        canonical 26-module map + status
  mNN_<key>/
    __init__.py
    SPEC.md          pointer to ABM_Enterprise_Platform/<folder>/ (full 18-section spec)
    service.py       stable import point; wired impl or NotImplementedError stub
```

## Live status via API
`GET /platform/modules` and `GET /platform/health` (router: routers/platform_status.py).

## How to extend
Pick a SCAFFOLD module, open its blueprint spec, implement against its
implementation checklist + acceptance criteria, flip its `status` in
registry.py to PARTIAL/LIVE, and wire `service.py` to the real code — exactly
how Module 08 (Journey/Sequence) was just done.
