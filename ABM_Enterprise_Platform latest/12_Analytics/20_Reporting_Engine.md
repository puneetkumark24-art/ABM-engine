# Module 20 — Reporting Engine

> **Domain folder:** `12_Analytics`  
> **Replaces / equivalent to:** HubSpot reports/dashboards + exports + scheduled digests.

## 1. Purpose
Turns analytics into consumable, shareable output: custom report builder, prebuilt dashboards, scheduled email digests, exports (PDF/CSV/XLSX), and the executive-brief generator (one-click pre-meeting PDF) — the presentation layer over the Analytics Engine.

## 2. Scope
**In scope**
- Report builder (pick metrics/dims/viz)
- Dashboard composition (11 role-based dashboards)
- Scheduled digests (daily/weekly)
- Exports: PDF/CSV/XLSX
- Executive Brief generator (account one-pager PDF)
- Sharing & permissions on reports

**Out of scope**
- Metric computation (Analytics)
- Attribution math (Attribution)
- Data storage

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Exec | Views dashboards/briefs |
| Manager | Builds & schedules reports |
| AE | One-click account brief before a meeting |

## 4. Data Entities & Schema

### `report`
A saved report.

```
id UUID pk; tenant_id UUID; name text; definition jsonb; viz enum(table,line,bar,funnel,kpi); owner_id UUID; shared_with jsonb
```

### `dashboard`
A composed dashboard.

```
id UUID pk; tenant_id UUID; key text; name text; widgets jsonb; role_scope text[]
```

### `schedule`
A scheduled delivery.

```
id UUID pk; report_id UUID null; dashboard_id UUID null; cron text; recipients text[]; format enum(pdf,csv,xlsx,html); enabled bool
```

### `brief`
Generated executive brief.

```
id UUID pk; account_id UUID; pdf_url text; generated_at; sections jsonb
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/reports` | Create a report. | 201 |
| `GET` | `/v1/reports/{id}/render` | Render report data/viz. | 200 |
| `POST` | `/v1/reports/{id}:export` | Export PDF/CSV/XLSX. | 200 |
| `POST` | `/v1/reports/schedules` | Schedule a digest. | 201 |
| `POST` | `/v1/briefs:generate` | One-click account exec brief PDF. | 200 |

## 6. Core Workflows
1. Build report over analytics metrics -> render/visualize -> optionally schedule digest -> exporter renders PDF/CSV/XLSX -> deliver via Email engine
2. Exec brief: gather account intelligence+committee+signals+pipeline+risks -> render PDF -> store as brief + asset

## 7. State Machine — `schedule`
**States:** enabled, disabled

**Transitions:** toggled; runs on cron

## 8. Events
**Publishes:** `report.exported`, `digest.sent`, `brief.generated`

**Subscribes:** `analytics.rollup.completed`, `schedule.tick`

## 9. Business Rules
- **REP-001:** Reports respect row-level permissions of the requesting user (no data leakage via reports).
- **REP-002:** Scheduled digests deliver via the platform Email engine (consistent deliverability).
- **REP-003:** Exec brief pulls only current, non-decayed intelligence.
- **REP-004:** Exports are tenant-scoped & access-logged.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `reports.build` | Manager, Analyst, Admin |
| `reports.read` | per share + role |
| `briefs.generate` | AE, Manager, Admin |

## 11. Validations
- report references valid metrics
- cron valid
- recipients authorized

## 12. Error Scenarios
- 403 unauthorized share
- 422 invalid report def
- 413 export too large -> async

## 13. Internal Integrations
Analytics (data), Attribution, Email Delivery (digests), Asset Library (brief storage), Admin (permissions)

## 14. Testing Requirements
- Row-level permission in reports
- Export fidelity PDF/CSV/XLSX
- Scheduled digest delivery
- Brief content freshness

## 15. Acceptance Criteria
- [ ] Build & schedule a weekly pipeline digest emailed as PDF
- [ ] Generate an exec brief PDF for an account in one click

## 16. Edge Cases
- Huge export -> async job + link
- Recipient lacks access to underlying data -> redacted/blocked
- Brief for account with sparse data -> graceful sections

## 17. Implementation Checklist
- [ ] report builder + renderer
- [ ] dashboard composer (11 prebuilt)
- [ ] exporters (pdf/csv/xlsx)
- [ ] scheduler
- [ ] exec-brief generator
- [ ] share permissions

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
