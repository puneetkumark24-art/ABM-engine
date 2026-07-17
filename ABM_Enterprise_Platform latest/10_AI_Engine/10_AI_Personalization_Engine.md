# Module 10 — AI Personalization Engine

> **Domain folder:** `10_AI_Engine`  
> **Replaces / equivalent to:** Jasper/Copy.ai/Clay AI columns + custom prompt stacks — content generation & personalization.

## 1. Purpose
The content-generation brain: turns intelligence (brief, persona, pain, signals) into channel-ready, on-brand, compliant copy — emails, subjects, LinkedIn messages, landing-page copy, proposals, case studies, meeting prep — via a governed prompt/orchestration layer with the 7-agent chain, QC guardrails, and PII anonymization.

## 2. Scope
**In scope**
- 7-agent chain: Signal Analyst->Account Research->Persona Psychology->Pain Inference->Strategy->Message Gen->QC
- Generators: email, subject, LinkedIn, landing page, proposal, case study, meeting prep, call summary
- Prompt Builder & template library
- Brand voice + teaser-discipline QC guardrails
- PII anonymization (no real names/emails to LLM)
- Predictive: intent, buying-stage, deal-probability, risk (scored assists)

**Out of scope**
- Delivery (channel engines)
- Storing final CRM records
- Model hosting (Integration/Admin config)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Requests a draft for a contact |
| Marketer | Bulk-generates campaign variants |
| System | Auto-drafts inside journeys |

## 4. Data Entities & Schema

### `generation`
One AI generation request+result.

```
id UUID pk; tenant_id UUID; kind enum(email,subject,linkedin,landing,proposal,case_study,meeting_prep,call_summary,brief); subject_type enum; subject_id UUID; prompt_id UUID; input_context jsonb; output text; qc jsonb; confidence numeric(4,3); status enum(draft,qc_passed,qc_failed,approved,rejected); model text; created_at
```

### `prompt`
Versioned prompt template.

```
id UUID pk; tenant_id UUID; kind enum; name text; template text; variables text[]; guardrails jsonb; version int; active bool
```

### `brand_voice`
Tenant brand/voice + rules.

```
id UUID pk; tenant_id UUID; tone text; do_rules text[]; dont_rules text[]; teaser_rules jsonb; glossary jsonb
```

### `prediction`
A predictive score for an entity.

```
id UUID pk; entity_type enum; entity_id UUID; kind enum(intent,buying_stage,deal_probability,risk); value jsonb; confidence numeric(4,3); created_at
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/ai/generate` | Generate content of a kind for a subject with context. | 200 Generation |
| `POST` | `/v1/ai/generate:bulk` | Bulk variant generation. | 202 job |
| `POST` | `/v1/ai/qc` | Run QC guardrails on a draft. | 200 |
| `POST` | `/v1/ai/prompts` | Create/version a prompt. | 201 |
| `POST` | `/v1/ai/predict` | Compute a prediction (intent/stage/probability/risk). | 200 |
| `PUT` | `/v1/ai/brand-voice` | Set brand voice & guardrails. | 200 |

## 6. Core Workflows
1. Request -> assemble context (intelligence brief + persona + signals) -> anonymize PII -> run agent chain -> QC guardrails (teaser discipline, brand, compliance) -> qc_passed => surface for human/auto approval; qc_failed => regenerate or flag
2. Predictions computed on demand + on key events, cached with confidence

## 7. State Machine — `generation`
**States:** draft, qc_passed, qc_failed, approved, rejected

**Transitions:** draft->qc_passed/qc_failed by QC; qc_passed->approved by human/autonomy; ->rejected

## 8. Events
**Publishes:** `ai.generation.created`, `ai.generation.qc_failed`, `ai.prediction.updated`

**Subscribes:** `intelligence.record.created`, `journey.step.ai`, `deal.created (proposal prep)`

## 9. Business Rules
- **AIP-001:** No real PII is sent to an external model — placeholders substituted, personalized locally.
- **AIP-002:** QC must pass before any generation is eligible for send (teaser discipline, brand, no leaked facts).
- **AIP-003:** C-suite content always requires human approval regardless of QC/autonomy.
- **AIP-004:** Every generation stores its prompt version + input context for reproducibility/audit.
- **AIP-005:** Predictions always carry confidence; never surfaced as certainties.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `ai.generate` | AE, Marketer, system |
| `ai.prompt.manage` | Ops, Admin |
| `ai.brandvoice.manage` | Marketing lead, Admin |

## 11. Validations
- prompt variables satisfied by context
- output non-empty
- confidence in [0,1]

## 12. Error Scenarios
- 422 missing context vars
- 409 QC failed (returns reasons)
- 503 model unavailable -> fallback model/queue

## 13. Internal Integrations
Intelligence Engine (context), Journey/Marketing (consumers), CRM (writes drafts/notes), Integration Layer (model providers), Admin (AI credits)

## 14. Testing Requirements
- PII never leaves in prompt (assert anonymization)
- QC catches leaked facts (BFSI teaser case)
- Prompt versioning reproducibility
- Predictive calibration on labeled set

## 15. Acceptance Criteria
- [ ] Generate a persona-tailored email that passes QC and cites the triggering signal
- [ ] c-suite draft forced to human review
- [ ] Bulk variants for A/B produced

## 16. Edge Cases
- Sparse context (no signals) -> generic-but-safe fallback, flagged low confidence
- Model returns unsafe/off-brand -> QC fail + regenerate
- Arabic output requested -> localized generation + RTL note

## 17. Implementation Checklist
- [ ] agent chain orchestrator
- [ ] QC guardrail service
- [ ] prompt registry + versioning
- [ ] anonymizer
- [ ] predictor set
- [ ] brand voice store
- [ ] model adapter via Integration Layer

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
