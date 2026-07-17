# Module 26 — AI Copilot

> **Domain folder:** `10_AI_Engine`  
> **Replaces / equivalent to:** HubSpot ChatSpot / Breeze — conversational interface over the whole platform.

## 1. Purpose
The natural-language interface to everything: 'Which banks should I call today?', 'How do I approach Riyad Bank?', 'Draft outreach to the Al Rajhi CDO', 'What changed on my accounts this week?' — a governed agentic copilot that queries the graph, invokes engines (with permission + compliance gates), and returns answers, briefs and actions. The realization of the zero-human-intervention vision as an assistant surface.

## 2. Scope
**In scope**
- Conversational NL query over graph/analytics
- Action invocation (create task, enroll, generate draft, move deal) via tool-calling
- Grounded answers with citations to intelligence/records
- Guardrails: permission-aware, compliance-gated, confidence-qualified
- Proactive suggestions (today's priorities, risks)

**Out of scope**
- The underlying data/logic (each engine)
- Model hosting (Integration Layer)
- Bulk content gen (AI Personalization — Copilot calls it)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Asks who/how/what-to-say |
| Manager | Portfolio questions |
| Exec | 'How's pipeline vs quota?' |

## 4. Data Entities & Schema

### `copilot_session`
A conversation.

```
id UUID pk; tenant_id UUID; user_id UUID; started_at; context jsonb
```

### `copilot_turn`
One Q/A turn.

```
id UUID pk; session_id UUID; question text; plan jsonb; tools_called jsonb; answer text; citations uuid[]; confidence numeric(4,3); at timestamptz
```

### `tool_binding`
Registered tool the copilot may call.

```
code text pk; label text; engine text; params_schema jsonb; required_permission text; compliance_gated bool
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/copilot/ask` | Ask a question / issue a command. | 200 turn |
| `GET` | `/v1/copilot/sessions/{id}` | Conversation history. | 200 |
| `GET` | `/v1/copilot/suggestions` | Proactive priorities for the user. | 200 |
| `GET` | `/v1/copilot/tools` | Available tools for this user (permission-filtered). | 200 |

## 6. Core Workflows
1. Ask -> intent+plan -> select tools (permission-filtered) -> query engines / analytics / graph -> if action: enforce permission + compliance gate + (autonomy) confirmation -> compose grounded answer w/ citations + confidence -> log turn
2. Proactive: daily job computes 'today's priorities' from NBA + scores

## 7. State Machine — `copilot_turn`
**States:** planned, executed, answered, blocked

**Transitions:** planned->executed on tool calls; ->answered; ->blocked if permission/compliance denies

## 8. Events
**Publishes:** `copilot.action.taken`, `copilot.query.answered`

**Subscribes:** `intelligence.nba.created`, `score.threshold.crossed`

## 9. Business Rules
- **COP-001:** Copilot can only call tools the user is permitted to (RBAC-filtered tool list).
- **COP-002:** Any action that sends/outreach passes the same consent/suppression/hold/autonomy gates — Copilot cannot bypass compliance.
- **COP-003:** Answers are grounded with citations to platform records; ungrounded claims are qualified/omitted.
- **COP-004:** Destructive/outreach actions require explicit user confirmation unless autonomy tier permits.
- **COP-005:** C-suite outreach via Copilot always requires human confirmation.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `copilot.use` | All (tool set filtered by role) |
| `copilot.actions.write` | per underlying engine permission |

## 11. Validations
- tool params schema-valid
- user permitted for tool
- citations resolve

## 12. Error Scenarios
- 403 tool not permitted
- 409 compliance gate blocked (explained)
- 422 ambiguous query -> clarify

## 13. Internal Integrations
Intelligence, CRM, Scoring, Analytics, AI Personalization, Journey, Rules, Admin (RBAC), Integration Layer (LLM)

## 14. Testing Requirements
- RBAC tool filtering
- Compliance gate blocks outreach via copilot
- Answer grounding/citations
- Confirmation on destructive actions

## 15. Acceptance Criteria
- [ ] 'Which banks should I call today?' returns ranked accounts with reasons + citations
- [ ] 'Draft outreach to Al Rajhi CDO' generates via AI Engine but flags human review (c-suite)

## 16. Edge Cases
- Ambiguous ask -> clarifying question not wrong action
- User lacks permission -> explains, offers permitted alternative
- LLM hallucination -> grounding check strips uncited claims

## 17. Implementation Checklist
- [ ] intent/planner + tool-calling
- [ ] permission-filtered tool registry
- [ ] grounding + citation checker
- [ ] compliance-gate enforcement
- [ ] proactive suggestions job
- [ ] session/turn logging

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
