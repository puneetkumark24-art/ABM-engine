# AI Intelligence Layer — Audit, Contradictions, and Qwen-Powered Agent Architecture
### For: drip_platform Modules 01 (Intelligence Engine), 02 (Signal Detection Engine), 10 (AI Personalization Engine), 26 (AI Copilot)
### Scope: everything from PostgreSQL onward. Crawling/RSS/scraping/scheduling/change-detection is out of scope — owned by whoever builds Module 02's collectors.

---

## PHASE 1–2 · Current-state audit (synthesized, not re-derived)

Three documents already measured this codebase with real rigor: `INDEPENDENT_AUDIT_REPORT.md` (evidence-only, 542 lines, scored every module), `transformation/CTO_REVIEW.md` (blunt second opinion, 48/100 overall), and `transformation/DUE_DILIGENCE_V2.md`. Re-running that measurement would be wasted effort — instead, here is what those three establish specifically about the intelligence/AI layer, which is this document's actual mandate:

| Component | Audit score | What's real | What's not |
|---|---|---|---|
| Signal Detection | 4/10 | EPIS decay/confidence stamping on signals (real, tested — this is the P1 work from `docs/Signal_Pipeline_Architecture.md`, now shipped as `etl/signal_decay.py`). Tender/partner classification (real). | 8-stream autonomous collectors (RSS only, out of your scope anyway per Phase 3 of this brief). Content-hash dedup, Arabic NLP, org-attribution NLP — absent. |
| AI Scoring | 5/10 | Bible-formula deterministic scorer, tested, matches T-SCORE-1 exactly. | No ML/model. Weights hardcoded in two places (duplicate logic — flagged below). No explainability store. |
| AI Personalization | 4/10 | Anonymized context pipeline, QC guardrails, c-suite human gate, pluggable model adapter (the *harness* is real). | **Zero LLM calls exist in the tree.** `ai_gen.py`/`decision.py`/`copilot.py` are deterministic rules behind an empty adapter hook (CTO Review's words: "AI does not exist here"). |
| Prompt Engine | 2/10 | Inline prompt strings. | No versioned registry, no A/B, no evals, no cost ledger — effectively not implemented as an engine. |
| Agents (as a concept) | Not scored separately | Worker jobs on a queue. | No planning, memory, reflection, vector search, RAG, embeddings. CTO Review: "NOT IMPLEMENTED." |

**The one-sentence version, which this document exists to fix:** the platform has an unusually good *harness* for AI — governance, guardrails, anonymization, human-gates, a clean module boundary — wrapped around an engine that has never actually called a model. The CTO Review's own six-month plan puts this at **M1, the single highest priority**: "LLM core (adapter impl, prompt registry, eval harness, cost tracking) — converts the existing harness into actual AI." This document is the detailed design for exactly that M1 item, using Qwen specifically (per your Phase 4 instruction) rather than a generic "model adapter."

### Contradictions found between existing documents (per your Phase 1 instruction)

**Contradiction 1 — two different decay/confidence architectures, not yet reconciled.**
`docs/Signal_Pipeline_Architecture.md` (this project's own prior design, now partially built) puts `confidence_score`, `decay_category` (OPERATIONAL/TACTICAL/STRATEGIC/STRUCTURAL), `decay_expires_at`, and `source_reliability` directly as columns on the `signals` table — already shipped in `models.py` and `etl/signal_decay.py`. Module 01's spec (`02_Intelligence/01_Intelligence_Engine.md`) instead proposes a **separate** `intelligence_record` table with its own `confidence numeric(4,3)` and `decay_expires_at`, decoupled from the raw signal. Module 02's spec (`03_Signal_Detection/02_Signal_Detection_Engine.md`) puts `decay_category enum(fast,medium,slow)` — a **third, incompatible enum** — directly on its own `signal` table definition, and uses `urgency enum(P1,P2,P3,P4)` where the actual shipped code uses `urgency` = CRITICAL/HIGH/MEDIUM/LOW.

**Recommendation:** these are not duplicates to merge — they're two genuinely different confidence concepts that need distinct names, not competing implementations of the same one. Keep `signals.confidence_score`/`decay_category`/`decay_expires_at` exactly as shipped (it answers "how much do I trust this raw fact, and for how long") and use `intelligence_record.confidence` for a *different* question — "how much do I trust this reasoned conclusion, which may synthesize five signals of varying individual confidence." The second should be computed *from* the first (an `evidence_ref` pointing at a signal inherits that signal's `confidence_score` as one input), never redefined independently. Standardize on the already-shipped OPERATIONAL/TACTICAL/STRATEGIC/STRUCTURAL decay taxonomy and CRITICAL/HIGH/MEDIUM/LOW urgency taxonomy everywhere — Module 02's `fast/medium/slow` and `P1–P4` specs should be corrected to match code, not the other way around, since the code is tested and shipped and the spec is not.

**Contradiction 2 — three separate "reasoning agent" taxonomies for overlapping work.**
The ABM Business Logic Bible's INT-SIG (§4.1.R) defines 8 reasoning streams (SIG-HYP, ACCESS_STRENGTH, SIG-VSAT, EXEC_BELIEF_TIMELINE, SIG-POWER, SIG-TENSION, SIG-MOBILITY, SIG-RELEVANCE). Module 01's spec collapses these to 5 ("HYP/VSAT/POWER/TENSION/MOBILITY"). Module 10's spec (AI Personalization) then defines its *own* 7-agent chain — "Signal Analyst → Account Research → Persona Psychology → Pain Inference → Strategy → Message Gen → QC" — where the first two steps (Signal Analyst, Account Research) are, on inspection, redoing work Module 01 already did.

**Recommendation, and this is the single highest-leverage cost-optimization decision in this whole design (Phase 4's mandate):** Module 10's content-generation chain must **consume** Module 01's `intelligence_record`/brief output as input context, never re-run signal analysis or account research itself. Collapse Module 10's 7-agent chain to 5 by deleting "Signal Analyst" and "Account Research" as separate LLM calls — they become a single context-fetch (Phase 8, Context Engine) reading Module 01's already-computed brief. This alone removes 2 of 7 Qwen API calls from every content-generation request, and — more importantly — prevents the two engines from silently disagreeing about the same account (Module 10 inventing its own "why now" narrative that contradicts Module 01's).

**Contradiction 3 — scoring duplication, confirmed independently by the audit.**
The audit's own words: "two scorers not unified; weights hardcoded in two places." This isn't a documentation contradiction, it's shipped duplicate logic (`scoring.py`'s Bible formula and a second dimension-based rescorer). Out of this document's direct scope (AI Scoring isn't one of the four modules assigned), but it matters here because Module 01's `nba_recommendation.expected_value` and the reasoning streams both need *one* authoritative score to read, not two that can disagree. Flagging for whoever owns scoring: unify before Module 01's NBA ranker goes live, or NBA ranking will inherit the same silent-disagreement bug as Contradiction 2.

---

## PHASE 3 · Scope boundary (restated, for the record)

Everything below assumes PostgreSQL already contains rows in `raw_capture` → `signal` → `signal_cluster` (Module 02's schema, as corrected above) written by collectors someone else builds. This design's job starts at "a relevant signal exists" and ends at "a grounded, cited, confidence-qualified answer, brief, or draft exists." No crawling, no scheduling, no change-detection is designed here.

---

## PHASE 4 · Qwen API design constraints (applied throughout, not bolted on)

Every agent design below is written against these constraints, because a design that ignores them would need a rewrite the moment it meets a real invoice:

- **Batching over per-item calls.** Signal-level classification agents (Tier A, below) never fire one Qwen call per signal. They batch N signals (default 10, capped by context window) into one structured-output call, since classification tasks are highly parallelizable and Qwen's per-request overhead (not per-token) dominates cost at small N.
- **Structured JSON output only, never free text parsed after the fact.** Every agent call specifies a JSON schema via Qwen's function-calling / structured-output mode. This is not a style preference — it's what makes `intelligence_record.body jsonb` and `generation.output text` reliably machine-parseable without a second "now extract the JSON from this prose" call (which the current stub code doesn't need to worry about, but a real integration will burn 2x cost on if not designed out up front).
- **Prompt caching on the system/developer prompt, always.** Every agent's system prompt (brand voice, EPIS rules, output schema, guardrails) is static per tenant and reused across every call for that tenant — this is precisely what Qwen's context caching is for, and it's why the Prompt Library (Phase 9) separates the static cacheable block from the per-call dynamic context block explicitly, not as one concatenated string.
- **Two-tier model routing.** Tier A (classification, extraction) uses the smallest capable Qwen model (`qwen-turbo`-class) — high volume, low reasoning depth, cost-sensitive. Tier B/C (synthesis, content generation, copilot) uses a larger model (`qwen-plus`/`qwen-max`-class) — lower volume, needs real reasoning. Routing by tier, not by a per-call decision, keeps the cost model predictable and auditable.
- **Retries: idempotent, bounded, and cost-aware.** A failed Qwen call retries against the *same* cached prompt with exponential backoff (3 attempts, matching `FAIL-02`'s pattern already established elsewhere in this project), and every retry is logged against the same `generation.id`/cost ledger row — a retry storm must show up as one expensive row, not three cheap ones nobody notices, closing the exact gap CTO Review flagged ("no cost tracking").
- **Async and parallel by default.** Tier A batch jobs and Tier B per-account synthesis run as async workers off the existing durable queue (`workflow_durable.py` — already real, per CTO Review's "keep forever" list) rather than inline in a request/response cycle. Only Copilot (Tier D, user-facing, synchronous by nature) and on-demand Email Personalization (a human clicked "draft this now") are synchronous Qwen calls.
- **Token budget is a first-class design input, not an afterthought** — this is what Phase 8 (Context Engine) exists to enforce.

---

## PHASE 5–6 · Agent architecture

### 5.0 The four tiers (the reconciliation of Contradiction 2, made structural)

```
TIER A — Signal Intelligence Agents        (cheap, high-volume, batched, qwen-turbo tier)
   reads: signal, signal_cluster              writes: signal fields, evidence_ref candidates
   cadence: triggered per new signal/cluster, batched hourly

TIER B — Synthesis & Reasoning Agents       (moderate volume, qwen-plus tier)
   reads: signal_cluster + graph (Phase 7)     writes: intelligence_record, hypothesis, nba_recommendation
   cadence: triggered on signal_cluster.promoted, or daily per active account

TIER C — Content Generation Agents          (on-demand, qwen-plus/max tier)
   reads: intelligence_record (Tier B output), never raw signals directly
   writes: generation
   cadence: on-demand (human request) or journey-triggered

TIER D — Copilot (orchestrator)             (on-demand, synchronous, qwen-max tier)
   reads: everything, via tool-calling into Tiers A/B/C and the graph
   writes: copilot_turn
   cadence: user-initiated
```

This tiering is the direct fix for Contradiction 2 and the direct implementation of Phase 4's cost-minimization mandate: expensive reasoning happens once per account per trigger (Tier B), gets stored, and is *read*, not recomputed, by everything downstream (Tier C, Tier D). A BD rep asking Copilot the same question about the same account twice in one day costs one Tier B synthesis call and two cheap reads, not two full reasoning passes.

### 5.1 Your requested agent list, mapped and consolidated

Twenty-seven agents were named in the brief. Running each as an independent LLM call per signal/account would violate Phase 4's cost mandate outright — most of them are really *dimensions of classification* that belong inside one Tier A batch call, or *views over* one Tier B synthesis, not separate model invocations. The table below is the honest mapping, including where consolidation happens and why:

| Requested agent | Tier | Consolidation decision |
|---|---|---|
| Bank Intelligence Agent | B | **This IS the core Tier B synthesis agent** (5.2 below) — not a separate thing from "Account Planning" or "Deal Intelligence"; those are views/outputs of the same synthesis. |
| Contact Intelligence Agent | B (sub-output) | A `subject_type=contact` `intelligence_record`, produced by the same reasoning-stream runner as Bank Intelligence, scoped to a person instead of an org. Not a separate agent. |
| Vendor Intelligence Agent | A + B | Vendor mentions are Tier A extraction (which vendor, what relationship) feeding SIG-VSAT reasoning (Tier B, already scoped in Module 01). Reuses `VendorIntelligence`/`vendor_intelligence` table already in the schema — no new table needed. |
| Executive Movement Agent | A | Full spec in 5.3. Classification agent: is this signal an exec move, and what does it imply. |
| Opportunity Detection Agent | B (sub-output) | An `nba_recommendation` with `action_code='pursue_opportunity'` — output of Bank Intelligence synthesis, not a separate model call. |
| Buying Signal Agent | A | A `signal.type` classification dimension already covered by Tier A's core classifier (5.4) — not a separate agent. |
| Digital Transformation Agent | A (taxonomy dim) | One value in the Tier A classifier's topic taxonomy, not a separate LLM call — see 5.4's consolidation note. |
| AI Adoption Agent | A (taxonomy dim) | Same as above. |
| Core Banking Agent | A (taxonomy dim) | Same as above. |
| Payments Agent | A (taxonomy dim) | Same as above. |
| Compliance Agent | A (taxonomy dim) + hard gate | Classification dimension in Tier A; *also* triggers the existing EDGE-04-style regulatory-pause hard gate (already specified in the Bible, §18) — not itself a generative agent. |
| Risk Agent | B (sub-output) | A `nba_recommendation`/`intelligence_record kind=risk` — Module 01 already scopes `kind enum(...,risk)`. Not separate. |
| News Intelligence Agent | A | Tier A classifier applied to `stream=news` raw_captures specifically — same agent as 5.4, filtered by stream. |
| Relationship Discovery Agent | B (sub-output) | SIG-PATH/SIG-MOBILITY reasoning, already in Module 01's scope. Consumes the knowledge graph (Phase 7) rather than being a separate call. |
| Product Recommendation Agent | B (sub-output) | An `nba_recommendation` cross-referencing `ProductFit`/`product` — reuses existing tables. |
| Cross Sell Agent | B (sub-output) | Same mechanism as Product Recommendation, scoped to existing-customer accounts. |
| Competitive Intelligence Agent | A + B | SIG-PARTNER classification (Tier A, **already built** — `etl/signal_intel.py`) feeding SIG-VSAT displacement reasoning (Tier B). |
| Email Personalisation Agent | C | Full spec in 5.5. |
| Executive Briefing Agent | C (consumes B) | A `generation kind=brief`, reads Module 01's brief output, formats for a specific exec audience. Full spec in 5.6. |
| Meeting Preparation Agent | C (consumes B) | A `generation kind=meeting_prep` — same mechanism as Executive Briefing, different template. |
| Account Planning Agent | B (view) | A read/aggregation over multiple `intelligence_record`s for one account, not a new generation. |
| Next Best Action Agent | B | **Core output of Tier B**, not a separate agent — `nba_recommendation` IS this agent's product. |
| Deal Intelligence Agent | B (sub-output) | `intelligence_record` scoped to `subject_type=opportunity`. |
| RFP Detection Agent | A | Already effectively built — the SIG-TENDER manual-entry + classification work from earlier this project. Automating it is a Tier A classifier applied to `stream=reg`/`stream=news`/`stream=vendor` captures, watching for tender/RFP language. |
| Procurement Agent | A (taxonomy dim) | Same mechanism as RFP Detection, broader — procurement activity short of a formal RFP. |
| Sales Coach Agent | D (Copilot skill) | A Copilot tool (`tool_binding`) that reads a rep's own activity + outcomes and suggests coaching — a Copilot query pattern, not a standing background agent. |
| Lead Scoring Agent | Out of this doc's scope | Owned by the existing (duplicate — see Contradiction 3) scoring engine; AI's role here is limited to feeding `prediction kind=deal_probability` as one *input* to that scorer, not replacing it. |
| Contact Prioritisation Agent | B (view) | A ranked read over `nba_recommendation` + existing `bd_priority`/`bd_flow_column` fields (already on `Person`) — not a new generation. |

**Net result: 27 requested "agents" become roughly 8 real background/on-demand agent types plus 1 orchestrator (Copilot), with the rest implemented as taxonomy dimensions, table views, or reused outputs.** This is the single most important design decision in this document, and it is a direct, literal application of Phase 4's "minimize API cost" instruction — 27 separate LLM agents each polling/running independently would be both incoherent (see Contradiction 2) and unaffordably expensive at "tens of thousands of contacts, hundreds of institutions" scale.

### 5.2 Bank Intelligence Agent (Tier B — the core synthesis agent)

**Purpose.** Turn a promoted `signal_cluster` for an account into `intelligence_record`s (hypotheses, why-now narrative, risk flags) and `nba_recommendation`s — the direct implementation of Module 01's reasoning streams (SIG-HYP/VSAT/POWER/TENSION/MOBILITY), and the single agent every other Tier B "sub-output" in the table above actually resolves to.

**Inputs.** `signal_cluster` (the triggering event), the account's existing `intelligence_record`s not yet superseded (so reasoning is incremental, not from-scratch every time), graph context from Phase 7 (subsidiaries, known vendors, buying committee), the account's current `AccountIntelligence`/scoring snapshot.

**Outputs.** One or more `intelligence_record` rows (`kind=hypothesis|narrative|risk`), zero or more `hypothesis` rows with competing explanations, zero or more `nba_recommendation` rows.

**Prompt strategy.** System prompt (cached): EPIS rules verbatim (never claim 1.0 confidence, always cite evidence, competing hypotheses not one guess, disconfirmation check required for HOT accounts). Developer prompt: the JSON output schema matching `intelligence_record`/`hypothesis`/`nba_recommendation` columns exactly. User/dynamic prompt: the specific signal_cluster + fetched context (bounded per Phase 8).

**Tools required.** Read access to the knowledge graph (Phase 7) via a scoped query tool, not raw SQL — the agent requests "buying committee for account X" and gets a bounded, pre-formatted context block, never an open-ended database connection.

**PostgreSQL tables used.** Reads: `signal`, `signal_cluster`, `intelligence_record` (prior, not-superseded), graph tables (Phase 7). Writes: `intelligence_record`, `hypothesis`, `nba_recommendation`, `evidence_ref`.

**Expected JSON output (abbreviated):**
```json
{
  "hypotheses": [
    {"statement": "...", "confidence": 0.62, "supporting_signal_ids": ["..."], "contradicting_signal_ids": []}
  ],
  "narrative": {"why_now": "...", "confidence": 0.71},
  "risk_flags": [{"statement": "...", "confidence": 0.4, "severity": "medium"}],
  "nba_candidates": [{"action_code": "escalate_rfp", "rationale": "...", "confidence": 0.8, "expected_value_hint": "high"}]
}
```

**Dependencies.** Module 02's signal/cluster pipeline must have run first (SIG-001: nothing becomes intelligence without provenance). Existing scoring engine for the account's current tier/score as context.

**Failure cases.** Sparse context (new account, few signals) → explicit low-confidence fallback, never a fabricated hypothesis (INT-002/EPIS-RCM-05 discipline, already established elsewhere in this project). Signal storm (100+ signals/hour on one account, per Module 01's own edge case) → dedup/cluster gate upstream must fire before this agent runs at all; the agent itself does not rate-limit, the Tier A/cluster layer does.

**Confidence score.** Every output field carries its own EPIS-calibrated confidence (never a single blanket score for the whole call) — this is INT-002's explicit requirement, not optional.

**Cost optimization.** Runs once per `signal_cluster.promoted` event (not per raw signal), and re-runs incrementally (only new clusters since last run) rather than reprocessing an account's full history each time. qwen-plus tier, single call per trigger.

**Caching strategy.** System prompt (EPIS rules + schema) cached per tenant. Prior intelligence_records for the account are NOT re-sent in full on every call — only a compact summary (Phase 8 governs exactly how compact).

**Memory strategy.** Long-term memory is the `intelligence_record` table itself (this agent's own prior outputs), not a separate vector store for v1 — matching the audit's finding that no vector/RAG infrastructure exists yet, and not inventing one before it's needed (see Open Questions).

**Retry logic.** 3 attempts, exponential backoff, against the same cached prompt; a permanently-failing cluster is flagged `NEEDS_REVIEW` (mirrors EDGE-UNK-02's human-review default) rather than silently dropped.

**Versioning.** Prompt version stored on every `intelligence_record` (via the `prompt.version` it was generated under) for reproducibility — directly satisfies AIP-004 (already specified in Module 10, applies equally here).

**Evaluation metrics.** Golden-file test (Module 01's own acceptance criterion): a fixed signal set must produce deterministic hypothesis ranking across runs, within confidence-score tolerance. Precision on "was this NBA actually taken and did it lead anywhere" tracked as a feedback loop into `prediction`.

### 5.3 Executive Movement Agent (Tier A — illustrative of the classification tier)

**Purpose.** Detect and classify executive-change signals (hire, departure, promotion, lateral move) from raw captures, and — critically — resolve SIG-MOBILITY's opportunity-transfer logic (an exec moving from Account X to Account Y re-anchors relevant intelligence at the new account).

**Inputs.** Batch of up to 10 raw_captures/signals pre-filtered to `stream=exec` or containing person-entity mentions.

**Outputs.** Structured classification per signal: is this an exec move (bool), move type, person entity (resolved against the existing `Person` table where possible, flagged `~inferred` where not), from-account/to-account, and — if the person is a known Decimal contact — an `Opportunity Transfer Event` flag that triggers Tier B re-synthesis at the destination account.

**Prompt strategy.** Batched structured-output call, qwen-turbo tier. System prompt: strict anti-fabrication (never invent a name/title not present in the source text), person-entity resolution rules.

**PostgreSQL tables used.** Reads: `signal` (batch), `Person` (for resolution). Writes: `signal` fields (type/urgency), triggers `nba_recommendation`/re-synthesis request at destination account rather than writing there directly.

**Expected JSON output:**
```json
{"results": [
  {"signal_id": "...", "is_exec_move": true, "move_type": "departure", "person_name": "...", "person_resolved_id": "uuid-or-null", "from_account_id": "...", "to_account_id": null, "opportunity_transfer": false}
]}
```

**Failure cases.** Ambiguous entity (common name, no LinkedIn/title corroboration) → `person_resolved_id: null`, flagged for Tier B to treat as low-confidence rather than blocking.

**Cost optimization.** Batched (10 signals/call), qwen-turbo, runs on the same hourly cadence as Tier A generally — not a bespoke schedule.

**Confidence / caching / retry / versioning / eval.** Same pattern as all Tier A agents (5.4) — this agent is a specialization of the general Tier A classifier, not an architecturally separate thing, which is itself a cost/complexity reduction versus running it as a standalone pipeline.

### 5.4 Signal Classification Agent (Tier A — the general-purpose workhorse)

**Purpose.** The single agent that most of the "taxonomy dimension" consolidations in 5.1's table actually resolve to. For every batch of new signals: classify type (leadership/regulatory/product/hiring/funding/tender/partnership/event/financial — matching Module 02's existing enum), topic tags (digital transformation / AI adoption / core banking / payments / compliance — as a multi-label array, not separate agents), urgency, and a first-pass relevance score feeding SIG-RELEVANCE's 4-axis filter.

**Inputs.** Batch of raw signals not yet classified.

**Outputs.** Per-signal: type, topic_tags[], urgency, relevance_axes {solution, initiative, narrative, opportunity} each 0–1.

**Tools required.** None beyond the LLM call itself — this agent does not need graph access, which is exactly why it's cheap and belongs at Tier A.

**Expected JSON output:**
```json
{"results": [
  {"signal_id": "...", "type": "tender", "topic_tags": ["digital_transformation", "core_banking"], "urgency_hint": "CRITICAL", "relevance": {"solutions": 0.9, "initiatives": 0.7, "narrative": 0.5, "opportunity": 0.85}}
]}
```

**Cost optimization.** This is where Phase 4's batching mandate matters most — this agent runs on every new signal, at volume, so it is qwen-turbo tier, batched at 10–20 signals/call, and is the primary driver of the platform's ongoing Qwen spend. Getting this one agent's cost-per-signal right matters more than any other single design decision in this document.

**Caching.** System prompt (taxonomy definitions, output schema) cached; per-batch content is the only variable part of the call.

**Retry.** Same 3-attempt backoff pattern; a batch that fails 3x splits into smaller batches before giving up (isolates a single malformed signal from blocking 9 good ones).

**Versioning / eval.** Classifier accuracy tracked against a human-labeled golden set (Module 02's own acceptance criterion: "football-sponsorship vs RFP correctly separated by relevance" is literally this agent's job).

### 5.5 Email Personalisation Agent (Tier C)

**Purpose.** Generate channel-ready email copy grounded in Tier B's intelligence_record output — the "Message Gen" step of Module 10's 7-agent chain (now 5, per Contradiction 2's fix), specifically for the email channel.

**Inputs.** `intelligence_record` (the brief for this account/contact), `brand_voice`, `prompt` (versioned template), anonymized contact context (PII substituted per AIP-001, already specified).

**Outputs.** A `generation` row (kind=email), draft subject + body, QC result.

**Prompt strategy.** System (cached): brand voice, teaser-discipline guardrails (never leak a specific proprietary fact that should stay behind a meeting, per the Bible's QC-PHIL irreversibility framing already established for this project). Developer: JSON schema for subject+body+cited_evidence_refs. User: the specific brief, anonymized.

**PostgreSQL tables used.** Reads: `intelligence_record`, `brand_voice`, `prompt`. Writes: `generation`.

**Failure cases.** C-suite target → AIP-003 hard gate, `status` forced to require human approval regardless of QC pass. Sparse brief → generic-but-safe fallback per Module 10's own edge case, flagged low confidence rather than fabricating personalization.

**Cost optimization.** Synchronous, on-demand (a human clicked "draft"), qwen-plus tier — not batched, since this is a one-at-a-time human-triggered action, but the *context* fed to it (Phase 8) is aggressively trimmed to only what the brief actually needs, not the account's full history.

**Caching / memory / retry / versioning / eval.** Standard Tier C pattern: prompt versioned (AIP-004), retried against model-unavailable per Module 10's own 503 error contract, evaluated via the QC guardrail pass rate + the existing Trust Preservation Score pattern established elsewhere in this project (a high QC-pass rate with declining downstream trust is a warning, not a success — that discipline applies here unchanged).

### 5.6 Executive Briefing Agent (Tier C, consumes Tier B)

**Purpose.** Format Tier B's synthesized intelligence into a role-appropriate brief — "what does the AE need before this call" vs. "what does the sales manager need for portfolio review" are different documents built from the *same* underlying `intelligence_record`, never two separate reasoning passes.

**Inputs/Outputs/tables.** Structurally identical to Email Personalisation (5.5) with `kind=brief`/`kind=meeting_prep` and a role-specific template selecting which fields of the intelligence_record to surface and at what depth.

**Cost note.** Because this reads Tier B output rather than re-synthesizing, generating both an AE brief and a manager brief for the same account costs one cheap formatting call each, not two expensive reasoning calls — this is Contradiction 2's fix paying off concretely.

### 5.7 Copilot Orchestrator (Tier D)

**Purpose.** The natural-language interface — Module 26 as specified, with the tool-calling layer wired to actually invoke Tiers A–C rather than the current stub.

**Inputs.** User question, session context (`copilot_session.context`), the permission-filtered `tool_binding` registry.

**Outputs.** `copilot_turn` — plan, tools called, grounded answer with citations, confidence.

**Prompt strategy.** System (cached): grounding discipline ("cite or omit," never assert without an evidence_ref/intelligence_record backing it — COP-003, already specified), tool-calling schema for the registered tools. Dynamic: the user's question + minimal session history (Phase 8 governs how much).

**Tools required.** Every `tool_binding` maps to a scoped read (query the graph, query `intelligence_record`/`nba_recommendation`) or a scoped write (invoke Tier C generation, create a task) — the Copilot itself never queries Postgres directly; it calls the same bounded tools every other agent uses, which is what makes COP-001's permission-filtering enforceable (a SQL-generating copilot cannot be permission-filtered reliably; a tool-calling one can).

**Failure cases.** Ambiguous query → clarifying question, not a guess (Module 26's own edge case). Destructive/outreach action → COP-004's confirmation gate, C-suite → COP-005's hard human-confirmation regardless of autonomy tier.

**Cost optimization.** Synchronous by necessity (a human is waiting), qwen-max tier for planning/answer composition, but every tool call it makes into Tiers A–C is itself already cost-optimized per their own sections above — the Copilot doesn't get a cost exemption, it inherits the cost discipline of everything it calls.

**Eval metrics.** Grounding rate (fraction of claims in an answer that trace to a real citation — Module 26's own acceptance criterion), tool-selection accuracy, and the existing RBAC test requirement (a copilot that occasionally calls a tool the user isn't permitted for is a security bug, evaluated as such, not a quality nit).

---

## PHASE 7 · Knowledge Graph

The audit is explicit that no vector store, embeddings, or graph database exists. The recommendation here is deliberately **not** to bolt on Neo4j/a vector DB for v1 — that would contradict this project's own Constitution ("KEEP·IMPROVE·EXTEND·HARDEN," never rebuild) and the CTO Review's explicit finding that the relational/RLS/multi-tenant foundation is genuinely strong. Instead:

**The graph is a relational graph, in Postgres, using the tables that already exist.** `Organization` + `OrgRelationship` (subsidiary/holding/vendor edges, already shipped) + `Person` + `PersonRelationship` + `VendorIntelligence` + the new `signal_cluster`/`intelligence_record`/`evidence_ref` tables from Modules 01–02 ARE the knowledge graph. What's missing is not a new database technology, it's a **query layer** that lets an agent ask graph-shaped questions ("who at this account reports to whom, and which of them has a warm path to Decimal") without hand-rolling recursive CTEs inside every agent's prompt-construction code.

**Recommended addition: a bounded graph-query tool, not a new store.** A single service (`graph_query.py`, new, thin) exposing operations like `get_buying_committee(account_id)`, `get_warm_paths(account_id)`, `get_subsidiary_tree(account_id)`, `get_vendor_relationships(account_id)` — each a parameterized, indexed query against existing tables, returning a compact JSON shape agents consume as tool results (this is literally the `tool_binding` mechanism Module 26 already specifies, reused for Tiers A–C as well as Copilot).

**Entities and relationships (mapped to existing/new tables):**

| Node type | Table | Edge type | Table |
|---|---|---|---|
| Bank/Organization | `Organization` | subsidiary_of, vendor_of, competitor_of | `OrgRelationship` (existing) |
| Person | `Person` | reports_to, connected_to, warm_path | `PersonRelationship` (existing) |
| Vendor/Product | `VendorIntelligence`, `Product` | powers, competes_with | `VendorIntelligence` fields (existing) |
| Signal/Event | `signal`, `signal_cluster` | about, evidences | `evidence_ref` (new, Module 01) |
| Intelligence | `intelligence_record`, `hypothesis` | explains, supersedes | own FK fields (new, Module 01) |
| Regulation | (new, small table) | applies_to | account-scoped join |
| RFP/Opportunity | `Opportunity`, `signal type=tender` | targets | existing FK |

**How AI uses this graph.** Every Tier B/D agent's context is assembled by calling 1–3 bounded graph queries (never a raw join across the whole database) before the Qwen call — this is precisely Phase 8's job, and is why the graph query layer and the context engine are designed together, not sequentially.

---

## PHASE 8 · Context Engine

**Purpose.** Decide, before every Qwen call, exactly what to fetch — this is the direct mechanism for Phase 4's "prevent unnecessary token usage" mandate, and the most commonly-skipped piece of AI system design (skipping it is exactly how a system ends up sending a whole account's history on every call, which is the failure mode CTO Review's "no cost tracking" finding implies is currently unguarded-against, since there's no real traffic yet to have hit the problem).

**Design, per agent tier:**

- **Tier A (classification):** no account context at all — a Tier A call is deliberately stateless, receiving only the batch of signal texts themselves. This is what keeps it cheap; resist any temptation to "add a bit of account context to improve accuracy" here, because that's exactly the scope creep that turns a $0.001/signal call into a $0.05/signal call at volume.
- **Tier B (synthesis):** fetches (a) the triggering `signal_cluster` in full, (b) up to the last 5 non-superseded `intelligence_record`s for the account, summarized to one line each (not full body — a compact `title` field exists in the schema specifically for this), (c) one graph query result (buying committee OR subsidiary tree OR warm paths — whichever the triggering signal type implies is relevant, not all three every time), (d) the account's current score/tier as a single number, not the full scoring history.
- **Tier C (content generation):** fetches only the *specific* `intelligence_record` the human selected (not the account's full intelligence history), the `brand_voice` row, and the specific `prompt` template — deliberately narrow, because content generation is about executing a known synthesis well, not re-discovering it.
- **Tier D (copilot):** fetches session history (last 3 turns, not the whole conversation) plus whatever the tool-calling plan determines it needs mid-conversation — this is the one tier where context is genuinely dynamic and query-driven rather than pre-determined, which is why it's also the most expensive tier per call and should stay the lowest-volume one.

**Token budget enforcement.** Each tier has a hard context token ceiling (Tier A: ~2k tokens/batch, Tier B: ~8k tokens/call, Tier C: ~4k tokens/call, Tier D: ~6k tokens/turn) — these are configuration, not architecture, but the *existence* of an enforced ceiling per tier (reject/truncate/summarize before sending, never silently send an oversized prompt) is the architectural requirement.

---

## PHASE 9 · Prompt Library (structure + representative examples)

Every prompt follows the same four-part structure, matching the `prompt` table's schema (`template`, `variables`, `guardrails`, `version`) already specified in Module 10:

**System Prompt** (cached, tenant-static): role definition, EPIS/guardrail rules, output JSON schema, anti-fabrication instruction. **Developer Prompt** (cached, tier-static): tool/function definitions if applicable, validation rules the model must self-check before returning. **User Prompt** (dynamic, per-call): the actual content to reason about, assembled by the Context Engine. **Expected JSON**: the exact schema, enforced via Qwen's structured-output mode, not hoped-for via instruction alone.

**Representative example — Tier B Bank Intelligence Agent:**

```
SYSTEM (cached):
You are the Intelligence synthesis agent for a B2B banking-sector ABM platform.
You reason from evidence only. Rules, non-negotiable:
1. Every hypothesis, narrative, or risk flag MUST cite at least one evidence_ref
   (a signal_id). Zero exceptions (INT-001).
2. Confidence is calibrated: 0.3-0.5 = weak/single-source, 0.5-0.75 = corroborated,
   0.75-0.95 = strongly corroborated. NEVER output 1.0 (EPIS-RCM-05).
3. When evidence supports multiple explanations, output multiple hypotheses.
   Do not collapse to one guess.
4. If context is sparse, say so explicitly via a "critical_unknowns" field.
   Do not fabricate to fill gaps.
5. Output ONLY the JSON schema below. No prose outside the JSON.

Output schema: { ...as in 5.2... }

DEVELOPER (cached):
Available graph tool results are provided pre-fetched in the user message under
"graph_context" — do not request further tool calls; reason only over what's given.
Self-check before returning: every hypothesis.supporting_signal_ids must reference
a signal_id actually present in the input. Reject your own draft and retry once
internally if this check fails.

USER (dynamic, per-call):
signal_cluster: { ...triggering event... }
prior_intelligence_summary: [ {title, confidence, created_at}, ... up to 5 ]
graph_context: { buying_committee: [...], subsidiary_tree: [...] }
current_score: { tier: "HOT", effective_opportunity: 71.2 }

VALIDATION RULES (enforced post-response, before DB write):
- every hypothesis.confidence in [0,1]
- every supporting_signal_id resolves to a real signal in this tenant
- if hypotheses is empty AND critical_unknowns is empty -> reject, retry (model
  must explain itself one way or the other)

GUARDRAILS:
- Refuse to generate an nba_recommendation targeting a C-suite contact without
  setting human_review_required=true (INT-005, hard-coded check, not model-trusted)
- Refuse to output confidence >0.95 (hard-clamped post-response regardless of
  model output, per EPIS-RCM-05 — belt AND suspenders, not model-trust-only)
```

The other seven agent specs in Phase 6 follow this identical four-part structure with tier-appropriate system prompts (Tier A's system prompt is the taxonomy definition + anti-fabrication rule; Tier C's is brand voice + teaser discipline; Tier D's is grounding + tool-calling contract) — not reproduced in full here to keep this document to a readable length, but every one of them is a direct instance of this same template, which is itself a design decision worth stating explicitly: **one prompt template shape across all four tiers**, not bespoke prompt engineering per agent, because a shared shape is what makes the eval harness (Phase 11) and the versioning/audit trail (AIP-004) actually maintainable at 8+ agent types.

---

## PHASE 10 · Final consolidated summary

**1. Current Architecture.** A genuinely well-engineered relational/multi-tenant backend (RLS, partitioning, durable queues — CTO Review's "keep forever" list) wrapped around an AI layer that is a harness with zero live model calls (CTO Review: "AI does not exist here"). Modules 01/02/10/26 are specified in reasonable depth but ~46 lines of actual code combined.

**2. Improved Architecture.** Four agent tiers (A: cheap batched classification, B: per-account synthesis, C: on-demand content generation, D: copilot orchestration) replacing the 27-agent flat list with ~8 real agent types plus consolidated taxonomy dimensions and table views — directly reconciling Contradiction 2 and directly serving the cost mandate.

**3. AI Architecture.** Qwen API only, two-tier model routing (turbo for Tier A, plus/max for B–D), structured JSON output everywhere, prompt caching on all static system/developer prompts, async workers for Tiers A/B off the existing durable queue, synchronous only for Tiers C (on-demand) and D (user-facing).

**4. Agent Architecture.** Full specs: Bank Intelligence (5.2), Executive Movement (5.3), Signal Classification (5.4), Email Personalisation (5.5), Executive Briefing (5.6), Copilot (5.7); consolidated mapping table for the remaining 21 requested agents (5.1).

**5. Data Flow.** `raw_capture` → (Module 02, out of scope) → `signal`/`signal_cluster` → Tier A classification (enriches `signal` fields) → Tier B synthesis on cluster promotion (`intelligence_record`/`hypothesis`/`nba_recommendation`) → Tier C on-demand generation (`generation`) and/or Tier D copilot queries (`copilot_turn`) — everything downstream reads, nothing downstream re-derives.

**6. Knowledge Graph.** Relational, in existing Postgres tables, not a new graph database — `Organization`/`OrgRelationship`/`Person`/`PersonRelationship`/`VendorIntelligence` plus new `evidence_ref` links, exposed to agents via a bounded `graph_query.py` tool layer, never raw SQL from an agent.

**7. Context Engine.** Per-tier fetch rules and hard token ceilings (Phase 8) — the concrete mechanism that makes "minimize API cost" real rather than aspirational.

**8. Prompt Library.** One four-part template (System/Developer/User/Validation+Guardrails) applied consistently across all agent tiers (Phase 9), versioned per the `prompt` table already specified.

**9. PostgreSQL Interaction.** No new tables beyond what Modules 01/02/10/26 already specify (corrected per Contradiction 1's enum fixes) plus one new small table for `regulation` (Phase 7) — this design is additive, not a schema rewrite, matching the Constitution's own KEEP/EXTEND rule.

**10. API Interaction.** Reuses the existing REST contracts already specified in each module (`/v1/intelligence/*`, `/v1/signals*`, `/v1/ai/*`, `/v1/copilot/*`) — this document specifies what runs *behind* those endpoints, not new endpoints.

**11. Cost Optimization Strategy.** Batching (Tier A), tiered model routing, prompt caching, read-don't-recompute across tiers (the Contradiction 2 fix), and hard per-tier token ceilings (Phase 8) — four independent cost levers, not one.

**12. Scalability Strategy.** Tier A/B run as async workers off the already-proven durable queue (idempotency keys, bounded backoff, DLQ — CTO Review's "keep forever" list); horizontal scaling is "add more workers," not an architecture change, because nothing in Tiers A/B is synchronous or stateful beyond what's already in Postgres.

**13. Security Considerations.** PII anonymization before any external Qwen call (AIP-001, already specified, must actually be implemented not just specified), RBAC-filtered tool access for Copilot (COP-001), C-suite hard human-gates regardless of autonomy tier (INT-005/AIP-003/COP-005 — three independent modules all specify this same gate; implement it once, shared, not three times independently or it will drift).

**14. Future Improvements.** A real vector store/embeddings layer becomes worth building only once semantic search over `intelligence_record`/signal text is a proven bottleneck for Copilot — not before (see Open Questions). Model fine-tuning on this project's own labeled golden sets, once enough eval history exists.

**15. Implementation Roadmap.**
- **Sprint 1:** Qwen adapter (real API calls replacing the stub), prompt registry (the `prompt` table, actually populated and versioned), cost ledger (log every call's tokens+cost against `generation.id`/a new lightweight cost-tracking table). This is CTO Review's M1, scoped concretely.
- **Sprint 2:** Tier A Signal Classification Agent (5.4) + Executive Movement Agent (5.3) — cheapest, highest-volume, proves the batching/caching pattern before Tier B commits to it.
- **Sprint 3:** Tier B Bank Intelligence Agent (5.2) + the graph_query.py tool layer (Phase 7) it depends on.
- **Sprint 4:** Tier C Email Personalisation (5.5) + Executive Briefing (5.6), consuming Sprint 3's output — proves the Contradiction 2 fix (no re-synthesis) end to end.
- **Sprint 5:** Copilot (5.7) wired to real tool-calling into Sprints 2–4's agents, plus the eval harness (golden sets, grounding-rate measurement) across everything built so far.

**16. Risks.** Qwen API latency/availability becomes a single point of failure for Tier D (user-facing, synchronous) — needs a fallback ("model unavailable, here's what I found without synthesis" per Module 10's own 503 contract) not a hard failure. Cost overrun if Tier A batching/caching isn't actually enforced in code (design compliance, not design correctness, is the real risk here — this document can be followed exactly and still overspend if the token ceilings in Phase 8 are configured but not enforced). Contradiction 1's enum reconciliation is a breaking migration if not sequenced correctly — do it before any Tier A/B code ships, not after.

**17. Open Questions.**
- **Vector store / RAG, now or later?** This document deliberately defers it (Phase 14) — recommend revisiting only once Copilot's grounding-rate eval (5.7) shows semantic-search misses as the actual bottleneck, not before, per this project's own Constitution against speculative infrastructure.
- **Which specific Qwen model tier for Tier B?** `qwen-plus` is assumed here as a reasonable default; the actual choice should be settled by a small eval comparing hypothesis-quality on a golden set against `qwen-max`, trading cost for reasoning depth — not decided architecturally in this document.
- **Where does the cost ledger live?** A new lightweight table alongside `generation`, or folded into the existing audit_log pattern already in the codebase? Leaning toward a dedicated table (cost queries have different access patterns than audit queries) but flagging as a genuinely open implementation choice, not a resolved one.
