# Module 22 — Attribution Engine

> **Domain folder:** `12_Analytics`  
> **Replaces / equivalent to:** HubSpot attribution + Bizible-style multi-touch models.

## 1. Purpose
Assigns credit for pipeline and revenue across the touches, campaigns, journeys and channels that influenced an account — multi-touch attribution models (first/last/linear/time-decay/W-shaped/custom) that turn the activity graph into ROI the Campaign and Reporting engines consume.

## 2. Scope
**In scope**
- Touch capture into attribution paths
- Attribution models: first, last, linear, time-decay, U/W-shaped, custom
- Account-based attribution (credit at account not just contact)
- Campaign/channel/journey ROI rollup
- Model comparison & configurable window

**Out of scope**
- Metric storage (Analytics)
- Report rendering (Reporting)
- Deal amounts (CRM/Pipeline)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Marketing lead | Chooses model, reads ROI |
| Exec | Revenue attribution |
| Analyst | Model comparison |

## 4. Data Entities & Schema

### `touch`
An attributable touch.

```
id UUID pk; tenant_id UUID; account_id UUID; contact_id UUID; channel enum(email,linkedin,event,web,content,call); campaign_id UUID null; journey_id UUID null; occurred_at timestamptz; weight numeric(4,3) null
```

### `attribution_path`
Ordered touches to an outcome.

```
id UUID pk; account_id UUID; deal_id UUID; touch_ids uuid[]; outcome enum(meeting,opportunity,won); value numeric; window_days int
```

### `attribution_result`
Credit per touch/campaign under a model.

```
id UUID pk; path_id UUID; model enum(first,last,linear,time_decay,u_shaped,w_shaped,custom); credit jsonb; computed_at
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/attribution/campaigns/{id}` | Attributed pipeline/revenue for a campaign. | 200 |
| `POST` | `/v1/attribution:recompute` | Recompute under a chosen model/window. | 202 |
| `GET` | `/v1/attribution/models:compare` | Compare credit across models. | 200 |

## 6. Core Workflows
1. Touches captured from events -> on outcome (meeting/opp/won) assemble attribution_path within window -> apply model(s) -> credit rolled to campaign/channel/journey -> feeds Campaign ROI & Reporting
2. Model change -> recompute results, keep history

## 7. State Machine — `attribution_result`
**States:** current, recomputed

**Transitions:** new model/window supersedes; history kept

## 8. Events
**Publishes:** `attribution.recomputed`

**Subscribes:** `email.event.clicked`, `linkedin.reply.received`, `form.submitted`, `meeting.booked`, `deal.stage.changed`

## 9. Business Rules
- **ATT-001:** A touch is credited to exactly one campaign per model run; multi-campaign split uses model weights (no double count).
- **ATT-002:** Attribution window configurable per tenant; touches outside window excluded.
- **ATT-003:** Account-based models can credit account-level touches to any contact's outcome at that account.
- **ATT-004:** Model choice is explicit; results always tagged with model+window.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `attribution.read` | Marketing, Exec, Admin |
| `attribution.configure` | Marketing lead, Admin |

## 11. Validations
- window>0
- model in enum
- path touches within window

## 12. Error Scenarios
- 422 unknown model
- 404 no path for deal

## 13. Internal Integrations
Analytics, Campaign (ROI), Reporting, CRM/Pipeline (outcomes)

## 14. Testing Requirements
- No double counting across campaigns
- Window exclusion
- Model math (W-shaped 30/30/30/10 etc.)
- Account-based credit

## 15. Acceptance Criteria
- [ ] Show campaign-attributed pipeline under linear vs W-shaped
- [ ] Change window and recompute

## 16. Edge Cases
- Outcome with zero prior touches -> direct/unattributed bucket
- Very long sales cycle beyond window -> partial path
- Touch shared by two journeys -> split by weights

## 17. Implementation Checklist
- [ ] touch capture
- [ ] path assembler
- [ ] model library
- [ ] account-based logic
- [ ] ROI rollup
- [ ] model comparison

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
