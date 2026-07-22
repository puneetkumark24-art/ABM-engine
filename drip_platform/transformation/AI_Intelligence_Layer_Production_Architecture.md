# Qwen-Powered AI Engine — Production Architecture (Part 2)
### Extends `AI_Intelligence_Layer_Architecture.md` (Part 1: agent tiers, knowledge graph, context engine, prompt template).
### This document adds: the Orchestrator, concrete Qwen integration mechanics, the full signal→CRM→marketing→notification pipeline, security, deployment, monitoring, and the module-by-module implementation plan. Still a design document — no code below is meant to ship as-is; it specifies exactly what Sprint 1 should build.

---

## 0 · What changed since Part 1, and why this isn't a rewrite

Part 1 designed the four agent tiers and reconciled three contradictions between existing specs. Since then I read the actual stub implementations Part 1's audit synthesis referred to (`abm_platform/services/ai_gen.py`, `decision.py`, `copilot.py`, `delivery.py`) rather than just their spec documents, plus the CRM/marketing/notification pipeline and `decimal_abm`'s real external channel adapters. Three things follow from that reading, and they reshape how Qwen gets wired in — for the better, because it means less new architecture is needed, not more.

**First:** every stub in this codebase already uses the identical pluggable-adapter pattern — `ai_gen.py`'s `register_model(fn)`, `decision.py`'s `register_policy(fn)`, `delivery.py`'s `register_transport(name, fn)`. This is a deliberate, consistent, already-proven convention across three independent modules, not an accident. **The Qwen integration should be one more instance of this same pattern, not a new architectural concept.** This materially simplifies the Orchestrator design in section 2 below.

**Second, a fourth contradiction, found by reading the code rather than the specs:** `drip_platform`'s Module 06/07 are explicitly building **native replicas** of HubSpot and Mailchimp ("CRM Engine (HubSpot Replica)", "Marketing Automation (Mailchimp replica core)" — verbatim from the module docstrings), and the only registered send transport is `dry_run` — nothing has ever left this system as a real email. Meanwhile `decimal_abm` (the separate, currently-live system) has **real, working** `HubSpotChannel` and `MailchimpChannel` (Mandrill) adapters that actually call `api.hubapi.com` and `mandrillapp.com`. Your Phase 7 instruction describes a pipeline ending in "→ HubSpot → Mailchimp → Notifications," which implicitly assumes the external-SaaS integration model — but the actively-developed codebase (`drip_platform`) is deliberately walking away from that model in favor of owning CRM and marketing natively. This is resolved in section 4.

**Third:** `copilot.py`, unlike `ai_gen.py` and `decision.py`, has **no adapter hook at all** — it's pure keyword-matched intent routing with no `register_llm()` seam. That's a real gap this design closes (section 2.3).

---

## 1 · System Architecture (updated)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CAPTURE (Module 02, out of scope — someone else's collectors)           │
│  raw_capture → signal → signal_cluster                                   │
└──────────────────────────────┬────────────────────────────────────────┘
                                │ event: signal.cluster.promoted
┌──────────────────────────────▼────────────────────────────────────────┐
│  AI ORCHESTRATOR (new — section 2)                                       │
│  routes to the right agent tier, builds context, calls Qwen, validates,  │
│  retries, caches, logs cost, writes results back                         │
│                                                                            │
│   ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────────┐      │
│   │ Context  │─▶│ Qwen Adapter │─▶│ Response   │─▶│ PostgreSQL   │      │
│   │ Engine   │  │ (register_   │  │ Validator  │  │ writer       │      │
│   │(Part 1 §8)│  │  model-style)│  │ + schema   │  │ (traceability│      │
│   └──────────┘  └──────────────┘  └────────────┘  └──────────────┘      │
└──────────────────────────────┬────────────────────────────────────────┘
                                │ intelligence_record / hypothesis / nba_recommendation
┌──────────────────────────────▼────────────────────────────────────────┐
│  BUSINESS RULES (existing — decision.py's compliance gates,              │
│  c-suite hard stops, EDGE catalogue, autonomy tiers — UNCHANGED,          │
│  the Orchestrator calls into these, never bypasses them)                 │
└───────┬───────────────────────┬──────────────────────┬─────────────────┘
        │                       │                       │
┌───────▼────────┐   ┌──────────▼──────────┐   ┌───────▼────────────┐
│ Dashboard        │   │ CRM Engine (m06)     │   │ Notification (m21)  │
│ (Flask, existing)│   │ + Marketing (m07)     │   │ + external bridge   │
│ reads             │   │ = system of record   │   │ (Slack/email/       │
│ intelligence_     │   │ (native replica,      │   │  in-app — section 4)│
│ record/nba directly│   │  section 4 resolves   │   │                      │
│                    │   │  the HubSpot/Mailchimp│   │                      │
│                    │   │  question here)        │   │                      │
└────────────────────┘   └───────────────────────┘   └──────────────────────┘
```

The Orchestrator is the only new architectural component in this whole document. Everything below and to the sides of it in the diagram already exists (as spec, stub, or working code) and is reused, not replaced — matching the Constitution's KEEP/EXTEND rule and directly answering "preserve what works, improve what doesn't."

---

## 2 · The AI Orchestrator (new component — full design)

### 2.1 Responsibility

One service (`abm_platform/services/ai_orchestrator.py`, new) that every agent tier calls through — no agent, and no calling code anywhere else in the platform, talks to the Qwen API directly. This single-chokepoint design is what makes cost tracking, retries, caching, and confidence scoring enforceable platform-wide instead of duplicated (or forgotten) in eight different agent implementations.

### 2.2 Interface (matches the existing adapter-registration convention exactly)

```python
# abm_platform/services/ai_orchestrator.py

def register_qwen_client(client) -> None:
    """One-time setup: the real Qwen API client (or a test double).
    Same pattern as ai_gen.register_model / decision.register_policy —
    nothing above this line needs to know it's Qwen specifically."""

def run_agent(db: Session, tier: str, agent: str, request: AgentRequest) -> AgentResult:
    """The single entry point every Tier A/B/C/D agent calls.
    1. Context Engine assembles input (Part 1 §8, per-tier token ceiling enforced here)
    2. checks prompt cache for this tenant+agent's static system/developer prompt
    3. calls Qwen (batched if tier==A, single call otherwise) with structured-output schema
    4. validates response against the agent's JSON schema (reject + retry once if invalid)
    5. computes/clamps confidence per EPIS-RCM-05 (never let the model's own number exceed 0.95 unchecked)
    6. writes result + full trace (prompt version, tokens, cost, latency) to PostgreSQL
    7. returns AgentResult; caller (the agent-specific code) applies its own business rules
    """
```

`AgentRequest`/`AgentResult` are typed dataclasses, not raw dicts — `request` carries `{tier, agent_name, subject_type, subject_id, context_override}` and `result` carries `{output: dict, confidence: float, model_used: str, tokens_in: int, tokens_out: int, cost_usd: float, latency_ms: int, cache_hit: bool, retries: int, trace_id: uuid}`. The trace_id is what "complete traceability" (your objective 5) actually means in practice — every field needed to answer "why did the system say this, what did it cost, and can I reproduce it" is on one row, not scattered across logs.

### 2.3 Closing the Copilot gap

`copilot.py` currently has no adapter hook. This design adds `register_llm_planner(fn)` to it, following the identical pattern — the planner function receives the question + permission-filtered tool registry and returns a tool-call plan, which `ask()` then executes exactly as it already executes the rule-based intents today. The existing keyword-routed intents (`call_list`, `approach`, `status`) become **fallback behavior when no LLM planner is registered** (useful for tests and for graceful degradation per objective 8's reliability requirement), not dead code to delete.

### 2.4 Batching mechanics (Tier A specifically)

The Orchestrator maintains a short-lived in-memory batch queue per tenant+stream: new `signal` rows land in the queue as they're created, and a background tick (every 60s, or when the queue hits 10 items, whichever first) flushes the batch as one Qwen call. This is a small, addressable piece of new code — not a generic streaming/message-bus system, which would be over-engineering relative to the actual volume this needs to handle at "hundreds of banks, 50k contacts."

### 2.5 Retry and circuit-breaking

Retries follow the same `FAIL-02` exponential-backoff pattern already established elsewhere in this project (3 attempts, capped). A NEW piece: if Qwen's API returns 5 consecutive failures across ANY agent within a rolling 2-minute window, the Orchestrator trips a circuit breaker and every `run_agent()` call short-circuits to a "model unavailable" `AgentResult` (confidence=0, a clear `degraded=true` flag) until a health-check call succeeds — this is the direct implementation of objective 8's "enterprise reliability" and closes the single-point-of-failure risk Part 1 already flagged (§Risks).

### 2.6 Cost ledger

A new table, `ai_cost_ledger` (deliberately separate from the general `audit_log`, resolving Part 1's own open question #3 in favor of a dedicated table — cost queries need date-range/tenant/agent aggregation that audit queries don't):

```
ai_cost_ledger
  id                uuid pk
  tenant_id         uuid
  trace_id          uuid          -- joins to the AgentResult that generated this row
  agent_tier        string        -- A/B/C/D
  agent_name        string
  model             string        -- qwen-turbo / qwen-plus / qwen-max
  tokens_in         int
  tokens_out        int
  cost_usd          numeric(10,6)
  cache_hit         bool
  latency_ms        int
  occurred_at       timestamptz
  __table_args__ = (Index on (tenant_id, occurred_at), Index on (agent_name, occurred_at))
```

Every `run_agent()` call writes exactly one row here, success or failure, cache-hit or not — this is what turns CTO Review's "no cost tracking" from a finding into a closed gap, and it's what Module 20 (Reporting Engine, already scaffolded) needs to build a real cost dashboard on top of, per objective 13.

---

## 3 · Qwen API Integration (concrete)

### 3.1 Auth and endpoints

Qwen is accessed via its OpenAI-compatible API surface (DashScope compatible-mode or Alibaba Cloud Model Studio, depending on your account region) — this matters architecturally because it means the Orchestrator's Qwen adapter can be written once against the OpenAI SDK's `chat.completions.create()` shape (base_url + api_key swapped), which is also what makes the "pluggable, swap the model later" requirement from `ai_gen.py`'s own docstring ("a Gemini adapter can be registered later behind the same interface") trivially satisfiable — the Orchestrator's adapter interface is model-agnostic by construction; Qwen is the first real implementation registered against it, not a hardcoded assumption baked into the Orchestrator itself.

### 3.2 Structured output

Every call sets `response_format={"type": "json_object"}` (or Qwen's function-calling mode where tool use is needed, e.g. Copilot's graph queries) with the JSON schema embedded in the developer prompt (Part 1 §9's template). The Orchestrator's response validator (2.2 step 4) is what actually enforces the schema post-hoc — never trust the model's `json_object` mode alone to guarantee schema conformance, since it guarantees valid JSON, not valid-*against-your-schema* JSON.

### 3.3 Model routing table (concrete defaults, tunable per Part 1 §Open Questions)

| Tier | Model | Rationale |
|---|---|---|
| A (classification, batched) | `qwen-turbo` | High volume, low reasoning depth, cost-dominant — smallest capable model. |
| B (synthesis) | `qwen-plus` | Real multi-step reasoning over graph context; default per Part 1, pending the eval-based decision flagged there. |
| C (content generation) | `qwen-plus` | Similar reasoning depth to B but shorter context; same tier is a reasonable default, revisit if copy quality under-performs. |
| D (Copilot) | `qwen-max` | User-facing, synchronous, lowest volume — the one place spending more per call for reasoning quality is justified. |

### 3.4 Prompt caching mechanics

Qwen's context-caching (where available on your plan tier) is invoked by structuring every call as `[cached_system_block, cached_developer_block, dynamic_user_block]` and reusing an identical `cached_system_block` string across calls for the same tenant+agent — the Orchestrator's prompt registry (section 2.2, backed by the existing `prompt` table from Part 1) is what guarantees byte-identical reuse; a single trailing-whitespace difference between calls defeats caching, which is why the registry stores the *exact* cached string once per version, not re-templated per call.

---

## 4 · Resolving Contradiction 4 — the HubSpot/Mailchimp question

**The recommendation: intelligence outputs write to the native CRM/Marketing engine (Module 06/07) as the system of record, and reach real HubSpot/Mailchimp only via the existing, already-working `decimal_abm` channel adapters as an explicit, optional bridge — not as the primary path.**

Reasoning: `drip_platform` is, by its own Constitution and by the `ABM_Enterprise_Platform latest` blueprint it's implementing, deliberately building HubSpot and Mailchimp *replacements*. Wiring the new AI layer's primary output path through the external SaaS APIs would be building against the system this project is actively trying to stop depending on. But `decimal_abm`'s live channels are real, tested, and currently the only way anything actually leaves this system today (`drip_platform`'s own transport is `dry_run`-only) — so they remain valuable as a bridge during the transition, exactly matching `MASTER_CONSOLIDATION_PLAN.md`'s own "non-corruption guarantee" (decimal_abm keeps running exactly as-is, nothing in this plan proposes turning it off).

**Concretely, the end-to-end flow your objective 7 asked for, corrected:**

```
signal.cluster.promoted
  → Orchestrator → Tier B Bank Intelligence Agent → intelligence_record + nba_recommendation
  → business rules (decision.py's existing compliance/c-suite gates, unchanged)
  → Dashboard (reads intelligence_record directly — already works, Flask templates exist)
  → CRM Engine m06 (writes Opportunity/ActivityLog — the native "HubSpot replica" system of record)
  → IF an nba_recommendation resolves to a real outreach action:
       → Tier C Email Personalisation Agent → generation (draft)
       → Marketing Engine m07 (the native "Mailchimp replica" — enqueues via delivery.py)
       → delivery.py's transport registry: "dry_run" today; a REAL transport can be registered
         here using decimal_abm's already-working MailchimpChannel (Mandrill) code, ported in
         as one more registered transport — not a new integration, a REUSE of proven code
  → Notification Engine m21 (in-app today; Slack/email channel adapters plug in via the same
    registration pattern once needed — NOT-001/NOT-002 quiet-hours logic already handles this)
```

If you specifically want data to also flow to a *real, external* HubSpot instance (e.g., because sales already lives in HubSpot day-to-day and won't adopt the native CRM UI yet), that's a legitimate, separate integration decision — port `decimal_abm/abm_engine/channels/hubspot_channel.py`'s working `HubSpotChannel` class in as an additional sync target off Module 06's `ActivityLog`/`Opportunity` writes, one-way (matching what it already does today: "logs every action to HubSpot," not two-way sync). This is flagged as an open question in section 8, not decided unilaterally here, because it's a product decision (which system does the sales team actually work in day to day) not an architecture one.

---

## 5 · Security

The audit already measured this precisely — Authentication 3/10, Authorization/RBAC 2/10, "reject-on-sight" findings including an unauthenticated LAN-exposed dashboard and a static JWT secret. This document's scope is the AI layer specifically, so rather than re-solving platform-wide auth (out of scope, already tracked in the transformation backlog), here is what the AI layer specifically must not make worse, plus what it must add:

- **PII never reaches Qwen.** `ai_gen.py`'s existing `_anonymize()` function is the enforcement point — the Orchestrator's Context Engine (Part 1 §8) must call through this exact function (or its Tier B/D equivalents, which don't yet exist and need building) before any context is assembled into a prompt, never construct prompts from raw `Person`/`Organization` rows directly. This is a code-review-enforceable rule, not just a design intention — recommend a lint/test rule that greps agent code for direct `person.primary_email`/`person.full_name` access outside the anonymizer.
- **Qwen API key is a secret, not a config value.** Given the audit's finding of a plaintext DB password in `.env`, the same mistake must not be repeated for the Qwen key — at minimum, out of `.env` and into whatever secrets mechanism the platform-wide security hardening (already on the transformation backlog) lands on; don't let the AI layer's Sprint 1 quietly reintroduce the exact anti-pattern the audit flagged elsewhere.
- **RBAC-filtered tool access for Copilot (COP-001) must be real, not aspirational.** Given the audit's finding that zero routers currently enforce route-level authorization, Copilot's tool-calling layer is a second, AI-specific instance of the same gap — a Copilot that can call any tool because nothing checks permissions is a bigger exposure than a normal unauthenticated route, because it's a natural-language interface that makes probing for what it *can* do trivial. This should not ship even in an internal-only Sprint without at least the tool-registry-level permission check COP-001 already specifies.
- **Cost-ledger and generation tables carry tenant_id and must respect the platform's existing RLS pattern** — CTO Review credits RLS-with-FORCE as genuinely proven infrastructure; the new `ai_cost_ledger`/agent output tables must be added to that same RLS policy set on creation, not bolted on later as an afterthought migration.

---

## 6 · Cost Optimization Strategy (consolidated — mechanisms specified across this doc and Part 1)

1. Tiered model routing (§3.3) — the single biggest lever, since Tier A volume dominates call count.
2. Batching (§2.4) — reduces Tier A's per-call overhead specifically.
3. Prompt caching (§3.4) — reduces token cost on the static portion of every call, which is often the majority of tokens for agents with rich guardrail/schema system prompts.
4. Context Engine token ceilings (Part 1 §8) — bounds the dynamic portion.
5. Read-don't-recompute across tiers (Part 1, Contradiction 2 fix) — Tier C/D never re-run Tier B's reasoning.
6. Circuit breaker (§2.5) — prevents a Qwen outage from generating a retry-storm cost spike.
7. The cost ledger itself (§2.6) — you cannot optimize what you don't measure; this is the prerequisite for tuning 1–6 with real data instead of guesses.

---

## 7 · Deployment Strategy & Monitoring/Observability

Both scored at or near 0/10 in the audit (Deployment 3/10, CI/CD 0/10, Observability 0/10, Monitoring 0/10) — this is real, unresolved platform-wide debt, and the AI layer inherits it rather than fixing it. Scoped honestly to what this document can responsibly claim:

**Deployment (AI-layer-specific piece only).** The Qwen adapter's configuration (API key, base URL, model routing table) should be environment-driven (dev/staging/prod distinct keys and, ideally, distinct rate-limit budgets) from day one, even while the platform as a whole remains single-machine — this costs nothing extra to do correctly now and avoids a painful retrofit when the platform-wide deployment work (CTO Review's M3) eventually lands on real cloud infrastructure.

**Observability (AI-layer-specific, buildable independent of platform-wide observability).** Because every `run_agent()` call already writes a full trace row (§2.2) and a cost-ledger row (§2.6), a minimal but genuinely useful observability surface exists *within the AI layer* without waiting for platform-wide OpenTelemetry: a dashboard page (reusing the existing Flask dashboard pattern) showing calls/min, cost/day, cache-hit rate, error rate, and p50/p95 latency per agent tier, queried directly from `ai_cost_ledger` and the trace table. This is explicitly a stopgap, not a replacement for real Prometheus/Sentry-grade monitoring — but it is achievable in Sprint 1 alongside the Qwen adapter itself, and it's what makes the cost/reliability claims in this document verifiable rather than assumed once real traffic exists.

**What this document does NOT claim to solve:** platform-wide CI/CD, real infra-level monitoring (Prometheus/OpenTelemetry/Sentry), multi-region HA, or the broader security hardening list — these are correctly scoped to the platform-wide transformation program already tracked in `transformation/BACKLOG.md`/`SPRINTS.md`, and duplicating that tracking here would create a fifth place these items are listed, which is exactly the kind of redundant-documentation problem CTO Review already flagged ("14+ governance/score markdown files").

---

## 8 · Implementation Roadmap (supersedes Part 1's roadmap with the Orchestrator/HubSpot findings folded in)

**Sprint 1 — Orchestrator + Qwen adapter + cost ledger.** Build `ai_orchestrator.py` (§2), register a real Qwen client behind `ai_gen.py`'s existing `register_model()` hook AND the new `register_qwen_client()` on the Orchestrator itself (both — `ai_gen.generate()` keeps working unchanged for callers that don't need Tier B/C sophistication yet), stand up `ai_cost_ledger`, build the minimal observability dashboard (§7). Exit criterion: one real Qwen call, traced end-to-end, cost logged, visible on the dashboard.

**Sprint 2 — Tier A: Signal Classification + Executive Movement agents** (Part 1 §5.3/5.4), wired through the Orchestrator's batching (§2.4). Exit criterion: Module 02's own acceptance test ("football-sponsorship vs RFP correctly separated") passes using real Qwen output, not the current stub.

**Sprint 3 — Tier B: Bank Intelligence Agent** (Part 1 §5.2) + the `graph_query.py` tool layer (Part 1 §7) it depends on. Exit criterion: Module 01's own acceptance criterion ("hypothesis set with calibrated confidence <5s") passes against real data.

**Sprint 4 — Tier C: Email Personalisation + Executive Briefing** (Part 1 §5.5/5.6), consuming Sprint 3's output, plus §4's resolution — port `decimal_abm`'s `MailchimpChannel` in as a registered `delivery.py` transport (still gated behind explicit opt-in, dry_run stays default). Exit criterion: a real (not offline-template) AI-drafted email, QC-passed, sent via the ported Mandrill transport in a controlled test, fully traced.

**Sprint 5 — Copilot** (Part 1 §5.7 + §2.3's new `register_llm_planner` hook), RBAC-gated tool access (§5), eval harness (grounding rate, per Part 1 §5.7) across everything built so far.

**Sprint 6 (new, not in Part 1) — CRM/Marketing sync + notification channels.** Wire Tier B's `nba_recommendation` output into Module 06's `Opportunity`/`ActivityLog` writes (§4's primary path) and Module 21's notification `send()` for real Slack/email channel adapters (currently in-app only). Exit criterion: the full diagram in §4 runs end-to-end on one real signal, from capture through a human seeing a notification.

---

## 9 · Open Questions (new, additive to Part 1's three)

- ~~Does sales actually need real external HubSpot, or does the native CRM replica suffice?~~ **RESOLVED (2026-07-21):** native CRM (m06) and native Marketing (m07) are the system of record — confirmed by Puneet. External HubSpot stays fully out of the primary path (no bridge, not even optional — this narrows §4 further than the original "bridge optional" framing). `decimal_abm`'s `MailchimpChannel` (Mandrill) still gets ported into `delivery.py` as a registered transport per Sprint 4, since it's the only proven way anything leaves the system today — but it's an implementation detail of the native Marketing engine's send path, not an external-system integration. Sprint 6's `Opportunity`/`ActivityLog` writes go to m06 only; no HubSpot sync code gets written.
- **Batching window tuning (§2.4's 60s/10-item defaults)** — reasonable starting guesses, not derived from real signal-volume data, since no real collector traffic exists yet (Module 02's collectors are out of this document's scope). Revisit once Sprint 2 has real volume to measure against.
- **Does Copilot's `register_llm_planner` replace or run alongside the existing keyword router?** This document recommends "alongside, as fallback" (§2.3) for reliability, but that means two code paths to maintain — worth revisiting once the LLM planner has enough production hours to trust as primary without a rule-based safety net.
