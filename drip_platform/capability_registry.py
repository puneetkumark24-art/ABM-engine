"""
capability_registry.py — the platform's structured self-knowledge (Unification
Step: Capability Registry).

One catalog of every capability: module, feature, status, competitor parity,
delivering sprint, and honest notes. This is THE source for the Feature Parity
Dashboard (/platform/parity) and the capability matrix — updated in code review
with every sprint, never from memory.

Status ∈ complete | partial | planned | blocked-external.
Parity percentages are honest engineering judgments of functional parity with
the named competitor's equivalent feature (not marketing claims).
"""
from __future__ import annotations

CAPABILITIES: list[dict] = [
    # ── CRM ──
    {"module": "CRM", "feature": "Companies/Contacts/Deals core", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 75, "Salesforce": 60},
     "notes": "8k+ real contacts on Postgres; tiering, org graph, outreach tracking"},
    {"module": "CRM", "feature": "Custom objects (dynamic types)", "status": "complete",
     "sprint": "S2", "parity": {"HubSpot": 70, "Salesforce": 50},
     "notes": "typed schema, strict validation, CRUD API; no UI builder yet"},
    {"module": "CRM", "feature": "Money-correct amounts (minor units)", "status": "complete",
     "sprint": "S2", "parity": {"HubSpot": 90, "Salesforce": 85},
     "notes": "amount_minor backfilled; forecasts money-correct"},
    {"module": "CRM", "feature": "Quotes / CPQ / price books", "status": "complete",
     "sprint": "S2", "parity": {"HubSpot": 65, "Salesforce": 40},
     "notes": "product+adhoc lines, discount/tax, SAR summaries; no e-sign/PDF yet"},
    {"module": "CRM", "feature": "Property & field history", "status": "complete",
     "sprint": "S2", "parity": {"HubSpot": 70, "Salesforce": 60},
     "notes": "audit-derived timeline; SCD-2 snapshots pending"},
    {"module": "CRM", "feature": "Pipelines / stages / forecast / health", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 70, "Salesforce": 55}},
    {"module": "CRM", "feature": "Meetings (schedule/conflicts/ICS export)", "status": "complete",
     "sprint": "FW1", "parity": {"HubSpot": 50, "Salesforce": 45},
     "notes": "meetings.py; calendar sync (Google/Outlook) credential-gated"},
    {"module": "CRM", "feature": "Calling / shared inbox", "status": "planned",
     "sprint": "S2-04b", "parity": {"HubSpot": 0, "Salesforce": 0}},
    {"module": "CRM", "feature": "Custom report builder (filters/group/sum)", "status": "complete",
     "sprint": "FW1", "parity": {"HubSpot": 45},
     "notes": "reporting.run_definition + saved reports; no drag-drop viz UI"},
    # ── Marketing ──
    {"module": "Marketing", "feature": "Campaigns / audiences / templates / A-B", "status": "complete",
     "sprint": "pre-S1", "parity": {"Mailchimp": 65, "HubSpot": 55}},
    {"module": "Marketing", "feature": "Journey orchestration (send/wait/branch)", "status": "complete",
     "sprint": "S3", "parity": {"Customer.io": 55, "Mailchimp": 60},
     "notes": "graph runner + tick; visual drag-drop builder pending (UI)"},
    {"module": "Marketing", "feature": "Multivariate testing + dynamic content", "status": "complete",
     "sprint": "S3", "parity": {"Mailchimp": 60, "HubSpot": 50}},
    {"module": "Marketing", "feature": "Real email transport (SES) + warmup", "status": "blocked-external",
     "sprint": "S3-01", "parity": {"Mailchimp": 0},
     "notes": "dry-run only by design; needs domain + SES credentials"},
    {"module": "Marketing", "feature": "Landing pages + forms + tracking pixels", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 50, "Mailchimp": 55}},
    {"module": "Marketing", "feature": "Dynamic segments + static lists", "status": "complete",
     "sprint": "PM1", "parity": {"Mailchimp": 55, "HubSpot": 50},
     "notes": "segments.py: condition rules incl. engagement join; static membership; no visual builder"},
    {"module": "Marketing", "feature": "Public preference center (signed links)", "status": "complete",
     "sprint": "FW1", "parity": {"Mailchimp": 60},
     "notes": "preferences.py: category opt-in/out, unsubscribe-all -> suppression, may_send() gate"},
    # ── Sales Engagement ──
    {"module": "Sales", "feature": "Multichannel sequences + engine", "status": "complete",
     "sprint": "pre-S1", "parity": {"Outreach": 55, "Apollo": 60}},
    {"module": "Sales", "feature": "Reply sentiment -> auto pause/suppress/handoff", "status": "complete",
     "sprint": "S5", "parity": {"Outreach": 60, "Salesloft": 55}},
    {"module": "Sales", "feature": "Step-level A/B (epsilon-greedy)", "status": "complete",
     "sprint": "S5", "parity": {"Outreach": 55}},
    {"module": "Sales", "feature": "Hot-lead prioritization", "status": "complete",
     "sprint": "S5", "parity": {"Apollo": 60, "Outreach": 50}},
    {"module": "Sales", "feature": "Dialer / meetings scheduler", "status": "planned",
     "sprint": "S2-04b", "parity": {"Outreach": 0}},
    # ── ABM Intelligence ──
    {"module": "ABM", "feature": "Buying-committee inference + coverage", "status": "complete",
     "sprint": "S4", "parity": {"Demandbase": 55, "6sense": 45}},
    {"module": "ABM", "feature": "Signal ingest + content-hash dedup", "status": "complete",
     "sprint": "S4", "parity": {"6sense": 40},
     "notes": "idempotent ingest; URL-dedup hardened in parity mission"},
    {"module": "ABM", "feature": "Live signal collectors (RSS framework + KSA sources)", "status": "complete",
     "sprint": "PM1", "parity": {"6sense": 35, "Demandbase": 30},
     "notes": "collectors.py: RSS/Atom, org matching, retry/auto-disable, scheduler; seeded Argaam/SAMA/ArabNews/SaudiGazette; LinkedIn/tender portals still absent"},
    {"module": "ABM", "feature": "Account scoring (signals+coverage blend)", "status": "complete",
     "sprint": "S4", "parity": {"6sense": 45, "Demandbase": 50}},
    {"module": "ABM", "feature": "Third-party enrichment (Apollo/Clay)", "status": "blocked-external",
     "sprint": "S4-03", "parity": {"Clay": 0, "Apollo": 0},
     "notes": "waterfall + provider registry built; needs data contract/API keys"},
    {"module": "ABM", "feature": "Intent data (bidstream)", "status": "blocked-external",
     "sprint": "S4-04", "parity": {"6sense": 0}},
    {"module": "ABM", "feature": "AI decision engine + autonomous loop", "status": "complete",
     "sprint": "pre-S1", "parity": {"6sense": 50},
     "notes": "offline policy + variant learning; LLM copilot seam ready"},
    # ── AI (Parity Mission) ──
    {"module": "AI", "feature": "Prompt registry + versioning + rollback", "status": "complete",
     "sprint": "PM1", "parity": {"HubSpot": 50},
     "notes": "llm_core.py: versioned prompts, active-version routing, rollback API"},
    {"module": "AI", "feature": "LLM provider adapters (Anthropic/OpenAI/Gemini)", "status": "complete",
     "sprint": "PM1", "parity": {"6sense": 40},
     "notes": "stdlib HTTPS adapters; honest dry-run without key; LIVE the moment a key is set (BLOCKED-EXTERNAL only for the key itself)"},
    {"module": "AI", "feature": "LLM cost/token tracking + prompt analytics", "status": "complete",
     "sprint": "PM1", "parity": {"HubSpot": 45},
     "notes": "llm_calls ledger; /ai/analytics per-prompt cost/tokens/errors"},
    {"module": "AI", "feature": "Prompt evaluation harness", "status": "complete",
     "sprint": "PM1", "parity": {"HubSpot": 40},
     "notes": "expect-contains case suites against active version"},
    {"module": "AI", "feature": "LLM wired into ai_gen guardrails", "status": "complete",
     "sprint": "PM1", "parity": {"6sense": 35},
     "notes": "enable_ai(): PII anonymization + QC + c-suite gates unchanged around live model"},
    {"module": "AI", "feature": "Agents / memory / RAG / embeddings", "status": "planned",
     "sprint": "PM2", "parity": {"6sense": 0, "Clay": 0}},
    # ── Workflow ──
    {"module": "Workflow", "feature": "Rules engine (trigger/condition/action)", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 55}},
    {"module": "Workflow", "feature": "Graph workflows + approvals", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 50, "Salesforce": 35}},
    {"module": "Workflow", "feature": "Durable execution (idempotency/retry/DLQ)", "status": "complete",
     "sprint": "S6", "parity": {"Salesforce": 45},
     "notes": "Temporal-style guarantees in-DB; visual builder pending (UI)"},
    # ── Analytics ──
    {"module": "Analytics", "feature": "Event firehose (partitioned) + funnels", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 55}},
    {"module": "Analytics", "feature": "Cohort retention + time series", "status": "complete",
     "sprint": "S7", "parity": {"HubSpot": 50}},
    {"module": "Analytics", "feature": "Attribution (first/last/linear)", "status": "complete",
     "sprint": "pre-S1", "parity": {"HubSpot": 45}},
    {"module": "Analytics", "feature": "Email analytics (opens/clicks/CTR/CTOR)", "status": "complete",
     "sprint": "U1", "parity": {"Mailchimp": 55, "HubSpot": 50},
     "notes": "unified endpoint over delivery_events; heatmaps/device split pending"},
    {"module": "Analytics", "feature": "Google Analytics 4 integration", "status": "blocked-external",
     "sprint": "U1", "parity": {"HubSpot": 0},
     "notes": "measurement-protocol seam built; needs GA4 property + api_secret"},
    {"module": "Analytics", "feature": "Warehouse (ClickHouse/Timescale) + BI", "status": "blocked-external",
     "sprint": "S7-02", "parity": {"Salesforce": 0}},
    # ── Developer Platform ──
    {"module": "Developer", "feature": "REST API (26 routers) + OpenAPI", "status": "complete",
     "sprint": "S2R-S10", "parity": {"HubSpot": 55}},
    {"module": "Developer", "feature": "API keys (hashed, scoped)", "status": "complete",
     "sprint": "S8", "parity": {"HubSpot": 65}},
    {"module": "Developer", "feature": "Outbound webhooks (signed, retried, DLQ)", "status": "complete",
     "sprint": "S8", "parity": {"HubSpot": 60}},
    {"module": "Developer", "feature": "GraphQL / SDKs / OAuth apps / marketplace", "status": "planned",
     "sprint": "S8-02", "parity": {"HubSpot": 0}},
    # ── Security & Compliance ──
    {"module": "Compliance", "feature": "Multi-tenant RLS (DB-enforced)", "status": "complete",
     "sprint": "pre-S1", "parity": {"Salesforce": 70}},
    {"module": "Compliance", "feature": "Route authz (JWT scopes) + audit trail", "status": "complete",
     "sprint": "S1", "parity": {"Salesforce": 55}},
    {"module": "Compliance", "feature": "Field encryption (Fernet) + RBAC/ABAC", "status": "complete",
     "sprint": "S9", "parity": {"Salesforce": 50}},
    {"module": "Compliance", "feature": "PDPL DSR (export/erase) + consent + retention", "status": "complete",
     "sprint": "S9", "parity": {"HubSpot": 60}},
    {"module": "Compliance", "feature": "SSO / MFA / SCIM", "status": "blocked-external",
     "sprint": "S9-02", "parity": {"Salesforce": 0}, "notes": "needs IdP tenant"},
    {"module": "Compliance", "feature": "SOC2 / ISO27001 / PDPL certification", "status": "blocked-external",
     "sprint": "S9-02", "parity": {"Salesforce": 0}, "notes": "needs external auditors"},
    # ── Platform / Ops ──
    {"module": "Platform", "feature": "Observability (logs/metrics/health)", "status": "complete",
     "sprint": "S1", "parity": {"ServiceNow": 45}},
    {"module": "Platform", "feature": "CI/CD + K8s + Terraform (me-south-1)", "status": "complete",
     "sprint": "S1", "parity": {"ServiceNow": 40},
     "notes": "declared + tested; not yet deployed to cloud"},
    {"module": "Platform", "feature": "SLOs + alerts + ops/DR runbooks", "status": "complete",
     "sprint": "S10", "parity": {"ServiceNow": 40}},
    {"module": "Platform", "feature": "Load proof @ 100k contacts/100M events", "status": "blocked-external",
     "sprint": "S10-02", "parity": {}, "notes": "needs staging infra"},
    # ── Workspace/UI ──
    {"module": "Workspace", "feature": "DRIP OS single application (SPA shell)", "status": "complete",
     "sprint": "OS1", "parity": {"HubSpot": 50},
     "notes": "one app at /: full IA sidebar, hash routing, shared account context, Account 360, ⌘K palette, notifications, one login; legacy console @ /legacy"},
    {"module": "Workspace", "feature": "BD outreach module inside the OS", "status": "complete",
     "sprint": "OS1", "parity": {"HubSpot": 45},
     "notes": "tier filter + outreach tracking via PATCH /crm/persons/{id}/outreach; Flask dashboard's ETL/flow-map screens remain @ :5050 (transition)"},
    {"module": "Workspace", "feature": "Global search (all entities)", "status": "complete",
     "sprint": "U1", "parity": {"HubSpot": 45}},
    {"module": "Workspace", "feature": "Executive dashboard (cross-module)", "status": "complete",
     "sprint": "U1", "parity": {"HubSpot": 45}},
    {"module": "Workspace", "feature": "Arabic RTL layout toggle", "status": "partial",
     "sprint": "FW1", "parity": {"Salesforce": 20},
     "notes": "dir/lang toggle persisted; full i18n string catalog pending"},
    {"module": "Compliance", "feature": "Login rate-limit + dashboard auth + audit retention", "status": "complete",
     "sprint": "FW1", "parity": {"Salesforce": 40},
     "notes": "closes 3 top audit security risks; retention wired into scheduler"},
]

_STATUS_WEIGHT = {"complete": 1.0, "partial": 0.5, "planned": 0.0, "blocked-external": 0.0}


def summary() -> dict:
    by_status: dict[str, int] = {}
    for c in CAPABILITIES:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    total = len(CAPABILITIES)
    done = sum(_STATUS_WEIGHT[c["status"]] for c in CAPABILITIES)
    return {"total_capabilities": total, "by_status": by_status,
            "completion_pct": round(100 * done / total, 1)}


def by_module() -> dict:
    mods: dict[str, dict] = {}
    for c in CAPABILITIES:
        m = mods.setdefault(c["module"], {"features": 0, "complete": 0, "items": []})
        m["features"] += 1
        m["complete"] += 1 if c["status"] == "complete" else 0
        m["items"].append({"feature": c["feature"], "status": c["status"],
                           "sprint": c["sprint"], "parity": c.get("parity", {}),
                           "notes": c.get("notes", "")})
    for m in mods.values():
        m["completion_pct"] = round(100 * m["complete"] / m["features"], 1)
    return mods


def parity_dashboard() -> dict:
    """Per-competitor average parity across the features where DRIP claims any
    parity mapping, plus the gap list (features at 0/blocked)."""
    comp: dict[str, list[float]] = {}
    gaps: list[dict] = []
    for c in CAPABILITIES:
        for name, pct in (c.get("parity") or {}).items():
            comp.setdefault(name, []).append(pct)
        if c["status"] in ("planned", "blocked-external"):
            gaps.append({"module": c["module"], "feature": c["feature"],
                         "status": c["status"], "sprint": c["sprint"],
                         "notes": c.get("notes", "")})
    return {"competitor_parity": {k: round(sum(v) / len(v), 1) for k, v in sorted(comp.items())},
            "top_gaps": gaps, "summary": summary(), "modules": by_module()}
