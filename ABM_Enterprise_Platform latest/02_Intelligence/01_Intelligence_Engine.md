# Module 01 — Intelligence Engine

> **Domain folder:** `02_Intelligence`  
> **Replaces / equivalent to:** The 'brain' — no direct external equivalent; the orchestration layer above Clay/Apollo/6sense intent.

## 1. Purpose
The central reasoning and orchestration layer that turns raw captured signals and enriched graph data into ranked, explained, action-ready intelligence. It owns the confidence model (EPIS), the reasoning streams (HYP/VSAT/POWER/TENSION/MOBILITY), and the 'why now / who / what to say' synthesis every downstream engine consumes.

## 2. Scope
**In scope**
- Signal reasoning streams and hypothesis generation
- EPIS confidence calibration on every derived fact
- Account/opportunity synthesis (why-now narratives)
- Next-Best-Action computation feeding CRM & Journey engines
- Intelligence briefs (account, persona, meeting)

**Out of scope**
- Raw capture (Signal Engine, 02)
- Contact/company enrichment I/O (Enrichment Engine, 03)
- Message copywriting (AI Personalization Engine, 10)
- Delivery of any kind

## 3. Personas
| Persona | Relationship to module |
|---|---|
| BD/AE | Consumes briefs & NBA, asks the Copilot 'who do I call' |
| Sales Manager | Reviews account narratives and risk flags |
| Platform (system) | Primary consumer — every engine reads intelligence outputs |
| Data Steward | Audits confidence calibration and reasoning provenance |

## 4. Data Entities & Schema

### `intelligence_record`
One synthesized intelligence item about an entity.

```
id UUID pk; tenant_id UUID fk; subject_type enum(account,contact,opportunity,vendor); subject_id UUID; kind enum(narrative,nba,risk,hypothesis,brief); title text; body jsonb; confidence numeric(4,3); evidence_refs uuid[]; decay_expires_at timestamptz; created_by enum(system,user); created_at timestamptz; superseded_by UUID null
```

### `hypothesis`
A competing explanation for a signal cluster with its own confidence (SIG-HYP).

```
id UUID pk; tenant_id UUID; signal_cluster_id UUID; statement text; confidence numeric(4,3); supporting_evidence uuid[]; contradicting_evidence uuid[]; status enum(open,confirmed,rejected); created_at timestamptz
```

### `nba_recommendation`
Next-Best-Action for an entity.

```
id UUID pk; tenant_id UUID; account_id UUID; action_code text; rationale text; confidence numeric(4,3); expected_value numeric; expires_at timestamptz; consumed_by UUID null; status enum(pending,taken,expired,dismissed)
```

### `evidence_ref`
Provenance pointer used by EPIS.

```
id UUID pk; source_type enum(signal,document,enrichment,activity); source_id UUID; reliability numeric(4,3); observed_at timestamptz
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/intelligence/accounts/{id}/brief` | Return the synthesized account brief (why-now, committee, risks, NBA). | 200 IntelligenceBrief; 404 |
| `GET` | `/v1/intelligence/accounts/{id}/nba` | Ranked Next-Best-Actions for an account. | 200 [NBA] |
| `POST` | `/v1/intelligence/hypotheses:generate` | Run reasoning streams over a signal cluster, return hypotheses w/ confidence. | 202 job; 200 [Hypothesis] |
| `POST` | `/v1/intelligence/records:query` | Filter intelligence records by subject/kind/min-confidence. | 200 paged |
| `POST` | `/v1/intelligence/records/{id}:supersede` | Mark a record stale and link its replacement. | 200 |

## 6. Core Workflows
1. Signal cluster promoted -> reasoning streams run -> EPIS stamps confidence -> intelligence_record persisted -> event intelligence.record.created emitted -> Scoring & CRM subscribe
2. NBA lifecycle: computed -> surfaced in CRM timeline -> taken/dismissed -> outcome feeds Lead Scoring

## 7. State Machine — `intelligence_record`
**States:** draft, active, decayed, superseded

**Transitions:** draft->active on EPIS pass; active->decayed at decay_expires_at; active->superseded when a newer record covers same subject/kind

## 8. Events
**Publishes:** `intelligence.record.created`, `intelligence.nba.created`, `intelligence.hypothesis.confirmed`

**Subscribes:** `signal.cluster.promoted`, `enrichment.entity.updated`, `activity.logged`

## 9. Business Rules
- **INT-001:** No intelligence_record may be persisted without >=1 evidence_ref.
- **INT-002:** confidence = f(evidence reliability, corroboration count, recency) via EPIS; never hardcoded to 1.0.
- **INT-003:** A record whose every evidence_ref is expired is auto-decayed nightly.
- **INT-004:** NBA expected_value must be recomputed if the underlying account score changes by >10 points.
- **INT-005:** C-suite-targeted NBAs are always flagged human_review_required regardless of autonomy tier.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `intelligence.read` | AE, Manager, Admin |
| `intelligence.hypothesis.generate` | Manager, Admin, system |
| `intelligence.record.supersede` | Data Steward, Admin |

## 11. Validations
- confidence in [0,1]
- subject_id must resolve within tenant
- decay_expires_at > created_at

## 12. Error Scenarios
- 422 no-evidence on persist
- 409 supersede loop (A supersedes B supersedes A)
- 404 unknown subject

## 13. Internal Integrations
Signal Engine (input clusters), Enrichment Engine (graph facts), Scoring Engine (consumes/refreshes), AI Personalization (brief -> copy), Copilot (query surface)

## 14. Testing Requirements
- Unit: EPIS confidence monotonicity (more corroboration never lowers confidence)
- Contract: brief schema stable
- Property: decayed records never surface in NBA
- Golden-file: fixed signal set -> deterministic hypothesis ranking

## 15. Acceptance Criteria
- [ ] Given a promoted cluster, a hypothesis set with calibrated confidence is produced <5s
- [ ] Account brief renders committee+why-now+top-3 NBA
- [ ] Superseded records disappear from all read APIs

## 16. Edge Cases
- Contradictory signals of equal reliability -> two open hypotheses, none auto-confirmed
- Zero contacts on account -> NBA = 'discover committee' not 'email CDO'
- Signal storm (100+ in an hour) -> dedup+cluster before reasoning to avoid brief spam

## 17. Implementation Checklist
- [ ] EPIS module + reliability table
- [ ] Reasoning stream runners (5)
- [ ] intelligence_record + hypothesis + nba tables & migrations
- [ ] brief assembler
- [ ] NBA ranker
- [ ] event pub/sub wiring
- [ ] decay job

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
