# Module 09 — Campaign Builder Engine

> **Domain folder:** `07_Marketing_Automation`  
> **Replaces / equivalent to:** HubSpot Campaigns + orchestration wrapper over ABM plays.

## 1. Purpose
The strategic wrapper that groups journeys, email campaigns, LinkedIn sequences, landing pages, assets and target account lists into a single named ABM campaign with objectives, budget, timeline, membership and unified ROI — the object leadership plans and reports against.

## 2. Scope
**In scope**
- Campaign object: objective, audience (account list), budget, timeline, owner
- Membership: journeys, email campaigns, sequences, assets, landing pages under one campaign
- Unified campaign analytics & ROI/pipeline attribution rollup
- Campaign templates (reusable ABM plays)

**Out of scope**
- Step execution (Journey/Marketing)
- Attribution math (Attribution Engine 18-attr)
- Asset storage (Asset Library 14)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Marketing lead | Plans & reports campaigns |
| AE | Sees campaign context on accounts |
| Exec | Reviews campaign ROI |

## 4. Data Entities & Schema

### `campaign`
ABM campaign.

```
id UUID pk; tenant_id UUID; name text; objective enum(awareness,demand,pipeline,expansion); status enum(planned,active,completed,archived); audience_account_list_id UUID; budget numeric; start_date date; end_date date; owner_id UUID; kpis jsonb
```

### `campaign_member`
Asset/journey/campaign linked under a campaign.

```
id UUID pk; campaign_id UUID; member_type enum(journey,email_campaign,sequence,landing_page,asset,form); member_id UUID
```

### `campaign_metric`
Rolled-up metric snapshot.

```
campaign_id UUID; date date; sends int; opens int; clicks int; replies int; meetings int; opportunities int; pipeline_value numeric; spend numeric
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/campaigns` | Create campaign (objective/budget/timeline). | 201 |
| `POST` | `/v1/campaigns/{id}/members` | Attach a journey/campaign/asset. | 201 |
| `GET` | `/v1/campaigns/{id}/roi` | Unified ROI/pipeline rollup. | 200 |
| `POST` | `/v1/campaigns:from-template` | Instantiate a reusable ABM play. | 201 |
| `GET` | `/v1/campaigns` | List/filter campaigns. | 200 |

## 6. Core Workflows
1. Plan campaign -> attach journeys/emails/assets/landing pages -> activate -> members execute -> metrics roll up nightly -> ROI vs budget & pipeline
2. Template play: pick play -> instantiate journeys+assets pre-wired -> assign account list

## 7. State Machine — `campaign`
**States:** planned, active, completed, archived

**Transitions:** planned->active on start; ->completed at end_date/goal; ->archived manual

## 8. Events
**Publishes:** `campaign.activated`, `campaign.completed`

**Subscribes:** `journey.goal.met`, `deal.stage.changed`, `email.event.*`, `meeting.booked`

## 9. Business Rules
- **CMP-001:** A campaign's ROI aggregates only members linked to it (no double count across campaigns via attribution weighting).
- **CMP-002:** Deactivating a campaign pauses its member journeys.
- **CMP-003:** Budget overrun flags the campaign and notifies owner.
- **CMP-004:** Account can be in multiple campaigns; attribution splits credit (see Attribution Engine).

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `campaign.manage` | Marketing lead, Admin |
| `campaign.read` | All |

## 11. Validations
- end_date>start_date
- audience list exists
- budget>=0

## 12. Error Scenarios
- 422 invalid timeline
- 404 member not found
- 409 member already linked

## 13. Internal Integrations
Journey/Marketing/LinkedIn/Landing/Asset engines, Attribution, Analytics/Reporting, Pipeline

## 14. Testing Requirements
- ROI rollup correctness
- Deactivate pauses members
- Template instantiation wiring
- Multi-campaign attribution split

## 15. Acceptance Criteria
- [ ] Build an ABM play grouping 2 journeys + landing page + asset list, activate, and see unified ROI
- [ ] Budget overrun alerts

## 16. Edge Cases
- Member journey shared by two campaigns -> attribution weighted, not doubled
- Campaign ends with live enrollments -> graceful drain or forced exit per setting

## 17. Implementation Checklist
- [ ] campaign + member + metric tables
- [ ] rollup job
- [ ] template instantiation
- [ ] budget monitor
- [ ] ROI view

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
