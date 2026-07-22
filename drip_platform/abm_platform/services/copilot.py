"""Module 26 — AI Copilot: natural-language interface over the platform.

Sprint 5 (AI Intelligence Layer) wires the Tier D orchestrator into the
seam this module's docstring always said would exist ("an LLM adapter can
be registered later") — but per the reconciliation discipline already
established in Sprints 1-4 (llm_core already being the one adapter seam,
qwen_client.py getting deprecated rather than duplicated), there is no
separate `register_llm_planner()` registry here: ai_orchestrator.run_agent
IS that seam, already pluggable, already degrading to an honest dry-run
with zero API cost when no provider is configured. Adding a second
registration mechanism on top would just be another "two systems not
unified" problem. When the Tier D calls succeed, `ask()` uses them; when
they don't (no provider configured, validation failure, circuit open), it
falls back to the original rule-based router below — unchanged, so every
existing caller of `ask(db, question)` keeps working exactly as before.

COP-001 (RBAC-filtered tools): the Copilot never queries Postgres
directly, even in its rule-based fallback paths below — it only reads via
the same bounded functions every other tier uses (graph_query, direct
read-only ORM queries scoped to safe fields). When a `user_id` is passed
to ask(), the tool catalog handed to the LLM planner is pre-filtered to
only the tools that user's role permits (admin.check_permission, the
existing ADM-002 deny-by-default RBAC check) — and execute_tool() checks
again at call time regardless of what the catalog said, so a
planner that (incorrectly) proposes a tool the user isn't permitted for
is refused, not executed. That double-check is deliberate: COP-001 is
explicit that "a copilot that occasionally calls a tool the user isn't
permitted for is a security bug," so permission is enforced at the one
place that actually matters (execution), not just at the point the model
saw the catalog.

COP-003: answers are grounded — every claim cites the record it came
from. COP-002: any action it takes goes through the owning engine's
gates (it can only *suggest* outreach, never send)."""
from __future__ import annotations
from datetime import datetime
import json
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_intel as mi
from abm_platform.services import admin, graph_query
from abm_platform.services import ai_orchestrator as orch

TIER = "D"

# ── RBAC-filtered tool registry (COP-001) ──────────────────────────────
# name -> (required_permission, fn(db, **kwargs) -> JSON-safe dict)
# Every tool is a bounded read — the Copilot has no write tools yet
# (COP-002: it can only suggest outreach, never send), so there is nothing
# here that needs a confirmation gate beyond the permission check itself.
TOOL_REGISTRY: dict[str, tuple[str, object]] = {
    "graph.buying_committee": ("crm.read", lambda db, org_id: graph_query.get_buying_committee(db, org_id)),
    "graph.warm_paths": ("crm.read", lambda db, org_id: graph_query.get_warm_paths(db, org_id)),
    "graph.vendor_relationships": ("crm.read", lambda db, org_id: graph_query.get_vendor_relationships(db, org_id)),
    "intelligence.recent_for_org": ("crm.read", lambda db, org_id: _intelligence_for_org(db, org_id)),
    "accounts.call_list": ("sequences.read", lambda db: {"answer": _call_list(db)[0], "citations": _call_list(db)[1]}),
    "platform.status": ("crm.read", lambda db: {"answer": _status(db)[0], "citations": _status(db)[1]}),
}

TOOL_DESCRIPTIONS = {
    "graph.buying_committee": "Buying committee members for an org_id, with role and reporting line.",
    "graph.warm_paths": "Person-to-person warm paths into an org_id.",
    "graph.vendor_relationships": "Known vendor/competitor relationships for an org_id.",
    "intelligence.recent_for_org": "Recent intelligence_records (hypotheses/narrative/risk) for an org_id.",
    "accounts.call_list": "Today's prioritized call list, no arguments needed.",
    "platform.status": "Platform-wide summary counts, no arguments needed.",
}


def _intelligence_for_org(db: Session, org_id: str) -> dict:
    rows = (db.query(mi.IntelligenceRecord)
            .filter(mi.IntelligenceRecord.org_id == org_id, mi.IntelligenceRecord.superseded_by_id.is_(None))
            .order_by(mi.IntelligenceRecord.created_at.desc()).limit(5).all())
    return {"records": [{"id": r.id, "kind": r.kind, "statement": r.statement, "confidence": r.confidence}
                        for r in rows]}


def list_tools(db: Session, user_id: str | None) -> dict[str, str]:
    """RBAC-filtered catalog handed to the LLM planner. user_id=None means
    an internal/trusted caller (no RBAC restriction — matches how the rest
    of the platform treats an absent actor elsewhere, e.g. sequences.engine
    running as the system); a real end-user call always passes user_id."""
    if user_id is None:
        return dict(TOOL_DESCRIPTIONS)
    out = {}
    for name, (perm, _fn) in TOOL_REGISTRY.items():
        if admin.check_permission(db, user_id, perm):
            out[name] = TOOL_DESCRIPTIONS[name]
    return out


def execute_tool(db: Session, name: str, args: dict, user_id: str | None) -> dict:
    """The ONLY place a tool actually runs. Re-checks permission here even
    though list_tools() already filtered the catalog — COP-001's own
    language ('occasionally calls a tool the user isn't permitted for is a
    security bug') means the enforcement point has to be execution, not
    just what the model was shown."""
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": f"unknown tool: {name}"}
    perm, fn = entry
    if user_id is not None and not admin.check_permission(db, user_id, perm):
        return {"error": f"permission denied: {name} requires {perm}", "denied": True}
    try:
        return fn(db, **(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} failed: {e}"}


_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_calls": {"type": "array", "items": {
            "type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}},
            "required": ["tool"]}},
        "clarify": {"type": "string"},
    },
}
_SYNTH_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}},
    "required": ["answer"],
}

_PLANNER_SYSTEM = (
    "You are the planning stage of an internal sales-intelligence copilot for "
    "Decimal Technologies. Given a question and a catalog of available tools, "
    "decide which tools (if any) to call to answer it. You may only call tools "
    "in the catalog — never invent a tool name. If the question is ambiguous "
    "(e.g. no organization named when one is required), set 'clarify' to a "
    "short clarifying question instead of guessing."
)
_SYNTH_SYSTEM = (
    "You answer a user's question using ONLY the tool results provided — never "
    "assert a fact that isn't grounded in them (COP-003: cite or omit). If the "
    "tool results are empty or don't answer the question, say so plainly rather "
    "than filling in generic content."
)


def _llm_ask(db: Session, question: str, user_id: str | None) -> mx.CopilotTurn | None:
    """Two-call plan-then-synthesize pattern. Returns None (never raises) on
    any failure so ask() can fall back to the rule-based router — the LLM
    path is strictly additive, never a hard dependency."""
    catalog = list_tools(db, user_id)
    if not catalog:
        return None

    plan_req = orch.AgentRequest(
        tier=TIER, agent_name="copilot_planner",
        system_prompt=_PLANNER_SYSTEM,
        developer_prompt=f"Available tools: {json.dumps(catalog)}. Return ONLY JSON matching: "
                         f"{json.dumps(_PLAN_SCHEMA)}",
        user_prompt=question, json_schema=_PLAN_SCHEMA,
        subject_type="copilot_question",
    )
    plan_result = orch.run_agent(db, plan_req)
    if plan_result.status != "ok":
        return None

    clarify = plan_result.output.get("clarify")
    if clarify:
        turn = mx.CopilotTurn(question=question, intent="clarify", answer=clarify, citations=[])
        db.add(turn); db.commit()
        return turn

    tool_results = []
    citations = []
    for call in plan_result.output.get("tool_calls", []):
        name = call.get("tool")
        if name not in catalog:
            # planner proposed a tool outside the RBAC-filtered catalog it was
            # given — refuse, don't execute, don't silently drop the fact that
            # this happened (COP-001 enforcement point)
            tool_results.append({"tool": name, "error": "not in permitted catalog — refused"})
            continue
        result = execute_tool(db, name, call.get("args", {}), user_id)
        tool_results.append({"tool": name, "result": result})
        if not result.get("error"):
            citations.append(f"tool:{name}:{json.dumps(call.get('args', {}))}")

    synth_req = orch.AgentRequest(
        tier=TIER, agent_name="copilot_synthesizer",
        system_prompt=_SYNTH_SYSTEM,
        developer_prompt=f"Return ONLY JSON matching: {json.dumps(_SYNTH_SCHEMA)}",
        user_prompt=json.dumps({"question": question, "tool_results": tool_results}),
        json_schema=_SYNTH_SCHEMA,
        subject_type="copilot_question",
    )
    synth_result = orch.run_agent(db, synth_req)
    if synth_result.status != "ok":
        return None

    answer = synth_result.output.get("answer", "")
    cites = synth_result.output.get("citations") or citations
    turn = mx.CopilotTurn(question=question, intent="llm_grounded", answer=answer, citations=cites)
    db.add(turn); db.commit()
    return turn


def ask(db: Session, question: str, user_id: str | None = None) -> mx.CopilotTurn:
    llm_turn = _llm_ask(db, question, user_id)
    if llm_turn is not None:
        return llm_turn

    q = (question or "").lower()
    if any(k in q for k in ("who should i call", "call today", "priorit")):
        intent, answer, cites = "call_list", *(_call_list(db))
    elif "how do i approach" in q or "approach" in q:
        intent, answer, cites = "approach", *(_approach(db, question))
    elif any(k in q for k in ("status", "summary", "where are we")):
        intent, answer, cites = "status", *(_status(db))
    else:
        intent = "unknown"
        answer = ("I can answer: 'Who should I call today?', 'How do I approach "
                  "<bank>?', or 'status'. (Free-form questions need the LLM "
                  "adapter, which isn't configured.)")
        cites = []
    turn = mx.CopilotTurn(question=question, intent=intent, answer=answer, citations=cites)
    db.add(turn); db.commit()
    return turn


def evaluate_grounding(db: Session, limit: int = 100) -> dict:
    """Module 26's own acceptance criterion (5.7): grounding rate — the
    fraction of recent turns that carry at least one citation. A high
    unknown/clarify rate isn't penalized (an honest 'I don't know' isn't an
    ungrounded claim); only turns that gave a substantive answer without
    any citation count against the rate."""
    turns = db.query(mx.CopilotTurn).order_by(mx.CopilotTurn.created_at.desc()).limit(limit).all()
    substantive = [t for t in turns if t.intent not in ("unknown", "clarify")]
    if not substantive:
        return {"turns_evaluated": 0, "grounding_rate": None}
    grounded = sum(1 for t in substantive if t.citations)
    return {
        "turns_evaluated": len(substantive),
        "grounded": grounded,
        "grounding_rate": round(grounded / len(substantive), 3),
        "intent_breakdown": {i: sum(1 for t in turns if t.intent == i) for i in {t.intent for t in turns}},
    }


def _call_list(db: Session):
    """Ranked by account priority + person tier + due sequence steps."""
    from sequences import engine as seq_engine
    due = seq_engine.get_due(db, limit=10, respect_send_window=False)
    lines, cites = [], []
    for r in due[:5]:
        p, e = r["person"], r["enrollment"]
        org = db.get(models.Organization, e.org_id) if e.org_id else None
        org_name = org.canonical_name if org else "—"
        lines.append(f"• {p.full_name} ({p.current_title or 'n/a'}) at {org_name} — "
                     f"tier {p.tier}, sequence step {r['next_step'].step_number} due")
        cites.append(f"enrollment:{e.id}")
    if not lines:
        # fall back to HOT accounts even with nothing due
        hot = (db.query(models.AccountIntelligence)
               .filter(models.AccountIntelligence.priority == "HOT").limit(5).all())
        for a in hot:
            org = db.get(models.Organization, a.org_id)
            lines.append(f"• {org.canonical_name if org else a.org_id} — HOT "
                         f"(score {a.effective_opportunity or a.score})")
            cites.append(f"account:{a.org_id}")
    answer = ("Today's priorities:\n" + "\n".join(lines)) if lines else \
             "Nothing due and no HOT accounts — check signal feed."
    return answer, cites


def _approach(db: Session, question: str):
    """Find the org named in the question; assemble committee + live signals."""
    orgs = db.query(models.Organization).all()
    target = None
    for o in orgs:
        if o.canonical_name and o.canonical_name.lower() in question.lower():
            target = o; break
        if o.short_name and o.short_name.lower() in question.lower():
            target = o; break
    if target is None:
        return "I couldn't match that organization. Try its exact name.", []
    persons = (db.query(models.Person)
               .filter(models.Person.current_org_id == target.id).all())
    now = datetime.utcnow()
    signals = [s for s in db.query(models.Signal).filter_by(org_id=target.id)
               .order_by(models.Signal.created_at.desc()).limit(10)
               if not (s.decay_expires_at and s.decay_expires_at < now)]
    cites = [f"org:{target.id}"] + [f"person:{p.id}" for p in persons[:5]] + \
            [f"signal:{s.id}" for s in signals[:3]]
    lines = [f"Approach plan for {target.canonical_name}:"]
    dms = [p for p in persons if p.persona == "Decision Maker" or p.is_decision_maker]
    champs = [p for p in persons if (p.persona or "") == "Champion"]
    if dms:
        lines.append("Decision makers: " + ", ".join(f"{p.full_name} ({p.current_title})" for p in dms[:3]))
    if champs:
        lines.append("Champion/bridge: " + ", ".join(p.full_name for p in champs[:2]))
    if signals:
        lines.append("Why now: " + "; ".join(s.title[:80] for s in signals[:2] if s.title))
    if not (dms or champs):
        lines.append("No committee mapped yet — enrich contacts first.")
    return "\n".join(lines), cites


def _status(db: Session):
    from abm_platform import registry
    n_orgs = db.query(models.Organization).count()
    n_persons = db.query(models.Person).count()
    n_signals = db.query(models.Signal).count()
    n_enroll = db.query(models.SequenceEnrollment).count()
    s = registry.summary()
    answer = (f"Platform: {s['total']} modules ({s['by_status']}). "
              f"Data: {n_orgs} organizations, {n_persons} contacts, "
              f"{n_signals} signals, {n_enroll} sequence enrollments.")
    return answer, ["registry:summary"]
