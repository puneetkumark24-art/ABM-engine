# Global Data Model & Shared Kernel

Every entity is tenant-scoped (`tenant_id`) with UUID primary keys, soft deletes, and audit history. Below is the shared kernel every module references; per-entity field schemas live in each module spec.

## Shared/global entities
| Entity | Description | Owning module |
|---|---|---|
| `tenant` | Workspace/org — root of multi-tenancy. | Admin (25) |
| `user / team / role` | Identity + RBAC. | Admin (25) |
| `account` | Target organization (bank/fintech/subsidiary/vendor). | Account Engine (05) |
| `contact` | Person at an account. | Contact Engine (04) |
| `company` | Non-target org / vendor / partner. | CRM (06) |
| `relationship` | Graph edge (org/person/vendor/tech). | CRM (06) / Graph |
| `signal / raw_capture` | Captured intelligence + provenance. | Signal Engine (02) |
| `intelligence_record / nba / hypothesis` | Reasoned intelligence. | Intelligence (01) |
| `deal / pipeline / stage` | Revenue objects. | CRM (06) / Pipeline (19) |
| `activity` | Universal interaction record. | CRM (06) |
| `campaign / journey / enrollment` | Orchestration objects. | Campaign (09)/Journey (08) |
| `email_campaign / message / delivery_event` | Marketing + delivery. | Marketing (07)/Delivery (11) |
| `account_score / lead_score / modifier` | Scoring. | Scoring (18) |
| `event` | Platform event (bus). | Integration Layer (24) |
| `audit_log` | Change history. | CRM (06)/Admin (25) |

## Conventions
- **PKs:** UUID v4/v7.
- **Tenancy:** `tenant_id` on every row; Postgres row-level security.
- **Timestamps:** `created_at`, `updated_at`, plus domain timestamps (`occurred_at`, `expires_at`).
- **Soft delete:** `deleted_at` nullable; never hard-delete production data.
- **JSONB** for flexible/config fields (definitions, blocks, payloads).
- **Partitioning:** `contacts`, `activities`, `events`, `email_message`, `delivery_event`, `metric_event` partitioned by tenant/time.
- **Materialized views:** analytics rollups, account graph, forecast.

## ER overview (textual)
```
tenant 1—* account 1—* contact
account 1—* deal *—1 pipeline 1—* stage
account 1—* signal *—1 raw_capture
account 1—* committee_member *—1 contact
(from)*—*(to) relationship  (org/person/vendor/tech graph)
contact 1—* activity ; deal 1—* activity
campaign 1—* campaign_member ; journey 1—* enrollment 1—* journey_event
email_campaign 1—* email_message 1—* delivery_event
account 1—* account_score ; contact 1—1 lead_score
event (bus) —> all consumers
```
