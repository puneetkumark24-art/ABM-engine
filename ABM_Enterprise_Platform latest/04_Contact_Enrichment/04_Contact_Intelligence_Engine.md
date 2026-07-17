# Module 04 — Contact Intelligence Engine

> **Domain folder:** `04_Contact_Enrichment`  
> **Replaces / equivalent to:** HubSpot Contacts + Apollo person records — the people system of record & scoring.

## 1. Purpose
System of record for people at scale (architected for 1M+ contacts): profile, career history, persona classification, decision authority, engagement history, and per-contact intelligence — the authoritative contact object every other engine references.

## 2. Scope
**In scope**
- Contact CRUD & bulk import
- Persona & seniority classification
- Decision authority / buying influence scoring
- Engagement history rollup
- Consent & suppression state on the person

**Out of scope**
- Company/account object (Account Engine)
- Committee role mapping (CRM Engine relationship layer)
- Message sending

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Owns and works contacts |
| Steward | Maintains data quality |
| System | Classifies & scores |

## 4. Data Entities & Schema

### `contact`
A person.

```
id UUID pk; tenant_id UUID; account_id UUID null; full_name text; first_name text; last_name text; title text; department text; seniority enum(c_suite,evp,svp,vp,director,manager,ic); persona_code text; decision_authority numeric(4,3); buying_influence numeric(4,3); email citext; email_status enum; phone text; linkedin_url text unique; country text; city text; consent_status enum(none,opted_in,denied); do_not_contact bool; owner_id UUID; lifecycle enum(subscriber,lead,mql,sql,opportunity,customer); created_at; updated_at; source text
```

### `career_event`
Job history / mobility.

```
id UUID pk; contact_id UUID; org_name text; title text; start_date date; end_date date null; is_current bool; detected_via enum(enrichment,signal_exec)
```

### `contact_engagement`
Rolled-up engagement stats.

```
contact_id UUID pk; opens int; clicks int; replies int; meetings int; last_interaction_at timestamptz; engagement_score numeric(4,3)
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/contacts` | Search/filter (title, seniority, account, persona, score). | 200 paged |
| `POST` | `/v1/contacts` | Create contact. | 201 |
| `PATCH` | `/v1/contacts/{id}` | Update fields (guarded). | 200 |
| `POST` | `/v1/contacts:bulk` | Bulk import CSV/JSON. | 202 job |
| `GET` | `/v1/contacts/{id}/timeline` | Unified activity timeline. | 200 |
| `POST` | `/v1/contacts/{id}:classify` | Recompute persona/authority. | 200 |

## 6. Core Workflows
1. Create/import -> enrichment triggered -> persona & authority classified -> engagement rollup subscribes to activity events -> mobility (SIG-EXEC) creates career_event + may transfer warm relationship
2. Consent change -> propagate do_not_contact everywhere

## 7. State Machine — `contact.lifecycle`
**States:** subscriber, lead, mql, sql, opportunity, customer

**Transitions:** advances on scoring thresholds & CRM deal linkage; can regress on disqualify

## 8. Events
**Publishes:** `contact.created`, `contact.updated`, `contact.classified`, `contact.consent.changed`, `contact.mobility.detected`

**Subscribes:** `enrichment.entity.updated`, `activity.logged`, `email.event.*`, `deal.stage.changed`

## 9. Business Rules
- **CON-001:** linkedin_url and verified email are unique identity keys per tenant.
- **CON-002:** do_not_contact=true blocks enrollment in any journey/campaign at enrollment time AND send time.
- **CON-003:** seniority c_suite forces human_review on any outreach (ties to autonomy ladder).
- **CON-004:** engagement_score feeds account Persona-Reachability (20%).
- **CON-005:** A contact with email_status invalid is do_not_email until re-verified.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `contacts.read` | All |
| `contacts.write` | AE, Steward, Admin |
| `contacts.bulk` | Steward, Admin |
| `contacts.delete` | Admin |

## 11. Validations
- email format + tenant-unique
- seniority in enum
- scores in [0,1]

## 12. Error Scenarios
- 409 duplicate identity key
- 422 invalid consent transition
- 413 bulk too large -> chunk

## 13. Internal Integrations
Account Engine, Enrichment, CRM Engine (committee), Marketing/Journey (enrollment gating), Lead Scoring

## 14. Testing Requirements
- Dedup on linkedin/email
- Consent propagation blocks send
- 1M-row import performance (batched)
- Timeline merges all channels in order

## 15. Acceptance Criteria
- [ ] Import 10k contacts deduped & enriched
- [ ] c-suite contact always flags review
- [ ] Consent denial removes from active journeys

## 16. Edge Cases
- Same person two accounts (board seats) -> primary + secondary affiliation
- Name-only contact (no email) -> enrichment queued, not enrollable
- Mobility to competitor -> relationship transfers, old edge archived

## 17. Implementation Checklist
- [ ] contact + career_event + engagement tables (partitioned)
- [ ] classifier
- [ ] bulk importer (chunked)
- [ ] timeline assembler
- [ ] consent propagation job

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
