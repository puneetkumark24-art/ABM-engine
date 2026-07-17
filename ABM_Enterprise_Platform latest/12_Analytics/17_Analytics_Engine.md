# Module 17 — Analytics Engine

> **Domain folder:** `12_Analytics`  
> **Replaces / equivalent to:** HubSpot Analytics + Mailchimp Reports + product analytics — metrics & funnels.

## 1. Purpose
Unified analytics across accounts, campaigns, journeys, pipeline, revenue, email, LinkedIn, AI performance and workflows — an event-sourced metrics layer with funnels, cohorts, conversion, response/meeting rates and dashboards, feeding both the Reporting Engine and the Copilot.

## 2. Scope
**In scope**
- Event ingestion from the platform event bus into an analytics store
- Metric definitions & aggregations (rollups, funnels, cohorts)
- Domain analytics: account, campaign, journey, pipeline, revenue, email, LinkedIn, AI, workflow
- Conversion funnels, response/meeting rates, CAC hooks
- Query API + materialized dashboards

**Out of scope**
- Attribution modeling (Attribution Engine 18-attr)
- Report rendering/export (Reporting Engine 20)
- Raw CRM object storage

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Manager/Exec | Reads dashboards |
| Marketer | Campaign performance |
| Analyst | Ad-hoc queries |

## 4. Data Entities & Schema

### `metric_event`
Normalized analytics event.

```
id UUID pk; tenant_id UUID; event_type text; subject_type text; subject_id UUID; props jsonb; occurred_at timestamptz
```

### `metric_def`
A defined metric.

```
id text pk; tenant_id UUID; name text; formula jsonb; grain enum(day,week,month); dimensions text[]
```

### `rollup`
Precomputed aggregate.

```
id UUID pk; metric_id text; dims jsonb; period date; value numeric
```

### `funnel`
A funnel definition + snapshot.

```
id UUID pk; tenant_id UUID; name text; steps jsonb; snapshot jsonb; updated_at
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/analytics/query` | Query metrics with dims/filters/grain. | 200 |
| `GET` | `/v1/analytics/funnels/{id}` | Funnel conversion snapshot. | 200 |
| `POST` | `/v1/analytics/metrics` | Define a metric. | 201 |
| `GET` | `/v1/analytics/dashboards/{key}` | Prebuilt dashboard payload. | 200 |

## 6. Core Workflows
1. Event bus -> analytics ingester -> metric_event store -> scheduled + incremental rollups -> dashboards/query API; funnels recomputed on cadence
2. Copilot/Reporting query metrics via query API

## 7. State Machine — `rollup`
**States:** stale, fresh

**Transitions:** marked stale on new events in period; recomputed to fresh by rollup job

## 8. Events
**Publishes:** `analytics.rollup.completed`, `analytics.anomaly.detected`

**Subscribes:** `* (all domain events)`, `email.event.*`, `deal.stage.changed`, `journey.step.executed`

## 9. Business Rules
- **ANL-001:** Metrics are tenant-isolated; no cross-tenant aggregation.
- **ANL-002:** Rollups are idempotent & reproducible from metric_events (event-sourced).
- **ANL-003:** Late-arriving events re-open the affected period for recompute.
- **ANL-004:** Anomaly detection flags large deltas (e.g. bounce spike) -> notify.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `analytics.read` | Manager, Marketer, Exec, Admin |
| `analytics.define` | Analyst, Admin |

## 11. Validations
- metric formula valid
- grain supported
- dimensions exist

## 12. Error Scenarios
- 422 invalid metric formula
- 413 query too broad -> require filters

## 13. Internal Integrations
All engines (events), Attribution, Reporting, Copilot, Notification (anomalies)

## 14. Testing Requirements
- Rollup reproducibility from events
- Late event recompute
- Tenant isolation
- Funnel math correctness

## 15. Acceptance Criteria
- [ ] Query meeting-rate by campaign by month
- [ ] Bounce-spike anomaly fires alert
- [ ] Dashboards load within SLA

## 16. Edge Cases
- Backfill historical events -> periods recompute
- High-cardinality dimension -> sampling/limits
- Timezone boundaries in day-grain rollups

## 17. Implementation Checklist
- [ ] event ingester
- [ ] metric_event store (columnar/partitioned)
- [ ] rollup engine
- [ ] funnel/cohort calc
- [ ] query API
- [ ] anomaly detector

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
