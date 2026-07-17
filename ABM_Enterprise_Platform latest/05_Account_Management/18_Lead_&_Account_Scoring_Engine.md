# Module 18 — Lead & Account Scoring Engine

> **Domain folder:** `05_Account_Management`  
> **Replaces / equivalent to:** HubSpot scoring + 6sense/MadKudu — the scoring math & Effective-Opportunity model.

## 1. Purpose
The quantitative core: computes the 0-100 account score (Signal 35% / Regulatory 30% / Reachability 20% / Relationship 15%), the Effective-Opportunity equation with its modifier chain, and contact-level lead scores — recalculated daily and on material events, driving tiering, routing and prioritization.

## 2. Scope
**In scope**
- Account base score (4 weighted dimensions)
- Effective-Opportunity = Dynamic_Score x ICS/100 x Stage x Budget x Entrenchment x Risk x Window
- Contact lead scoring (fit + engagement)
- Modifier lookup table (Bible Artifact 1)
- Daily recompute + event-driven recompute
- Score history & explainability

**Out of scope**
- Tier assignment/holds (Account Engine consumes score)
- Signal reasoning (Intelligence)
- Engagement capture (Delivery/Contact)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| System | Recomputes scores |
| Manager | Reviews score drivers |
| AE | Sorts by Effective-Opportunity |

## 4. Data Entities & Schema

### `account_score`
Daily account score snapshot.

```
id UUID pk; tenant_id UUID; account_id UUID; signal numeric; regulatory numeric; reachability numeric; relationship numeric; base_score numeric(5,2); effective_opportunity numeric; modifiers jsonb; computed_at timestamptz
```

### `lead_score`
Contact-level score.

```
id UUID pk; contact_id UUID; fit numeric; engagement numeric; total numeric(5,2); grade enum(A,B,C,D); computed_at
```

### `modifier`
Modifier lookup entry.

```
id UUID pk; kind enum(ics,stage,budget,entrenchment,risk,window); condition jsonb; multiplier numeric(4,3)
```

### `score_event`
Explainability record.

```
id UUID pk; account_id UUID; delta numeric; reason text; at timestamptz
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/scoring/accounts/{id}` | Current score + dimension breakdown + modifiers. | 200 |
| `POST` | `/v1/scoring/accounts/{id}:recompute` | Force recompute. | 200 |
| `GET` | `/v1/scoring/accounts/{id}/history` | Score over time + drivers. | 200 |
| `PUT` | `/v1/scoring/modifiers` | Update modifier table. | 200 |
| `GET` | `/v1/scoring/contacts/{id}` | Lead score + grade. | 200 |

## 6. Core Workflows
1. Daily job recomputes all active accounts; material events (new signal, engagement, stage move) trigger targeted recompute -> base score -> apply modifier chain -> effective_opportunity -> emit score.updated -> Account Engine re-tiers
2. Explainability: each recompute writes score_event deltas with reasons

## 7. State Machine — `account_score`
**States:** current, superseded

**Transitions:** new snapshot supersedes previous; history retained

## 8. Events
**Publishes:** `score.updated`, `score.threshold.crossed`

**Subscribes:** `signal.created/expired`, `email.event.*`, `deal.stage.changed`, `enrichment.entity.updated`, `relationship changes`

## 9. Business Rules
- **SCO-001:** Base = 0.35*signal + 0.30*regulatory + 0.20*reachability + 0.15*relationship (weights configurable, must sum to 1).
- **SCO-002:** Effective-Opportunity applies the full modifier chain from the lookup table.
- **SCO-003:** Only non-expired signals contribute to the signal dimension.
- **SCO-004:** A >10-point base change forces NBA/Effective-Opportunity refresh.
- **SCO-005:** Every score change is explainable (score_event with reason).

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `scoring.read` | All |
| `scoring.modifiers.manage` | Manager, Admin |
| `scoring.recompute` | Manager, Admin, system |

## 11. Validations
- weights sum to 1
- multipliers>0
- dimensions in [0,100]

## 12. Error Scenarios
- 422 weights!=1
- 404 unknown account
- 409 modifier condition invalid

## 13. Internal Integrations
Account Engine (tiering), Intelligence (NBA), Signals/Contact/CRM (inputs), Analytics

## 14. Testing Requirements
- Weight-sum guard
- Expired signals excluded
- Modifier chain correctness vs Bible table
- Explainability completeness
- Threshold-cross event

## 15. Acceptance Criteria
- [ ] Recompute yields the same number as the Bible worked example for a fixture account
- [ ] Score change re-tiers account & logs reasons

## 16. Edge Cases
- All signals expired -> signal dim=0, score reflects other dims
- New account no data -> baseline low score, not error
- Weight reconfig -> full recompute

## 17. Implementation Checklist
- [ ] dimension calculators
- [ ] modifier lookup table + loader
- [ ] effective-opportunity computer
- [ ] daily + event recompute jobs
- [ ] score history + explainability

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
