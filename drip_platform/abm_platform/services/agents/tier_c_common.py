"""
tier_c_common.py — shared implementation for Tier C content agents
(Email Personalisation 5.5, Executive Briefing 5.6). Per section 5.6:
"structurally identical to Email Personalisation with kind=brief/
meeting_prep and a role-specific template" — so rather than duplicating
the orchestrator-call/QC/human-gate wiring in two files, both agents call
generate_content() here with a different `kind` and `role_template`.

Deliberately reuses ai_gen.py's existing AIP-001/002/003 machinery
(_anonymize, qc_check, the c-suite human-gate rule) and writes to the
SAME mx.AiGeneration table ai_gen.generate() already writes to — this is
the KEEP·IMPROVE·EXTEND philosophy applied concretely: Tier C agents are
a smarter content SOURCE feeding the existing QC/approval pipeline, not a
parallel one. The dashboard's existing approve/reject UI for
ai_generations rows works unchanged for AI-orchestrator-produced content.

Grounding discipline (Phase 6 "cite or omit", reused here ahead of
Copilot/Sprint 5): every generation must cite which intelligence_record(s)
it drew from. cited_evidence_refs is stored in input_context for
inspection; a generation with an empty citation list on a non-empty
intelligence context is treated as a QC failure (ungrounded content is
exactly the failure mode EPIS-RCM-05 exists to prevent).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

import models
import models_ext as mx
import models_intel as mi
from abm_platform.services import ai_orchestrator as orch
from abm_platform.services import ai_gen

TIER = "C"

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "cited_evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "body"],
}


def _validate(d: dict) -> list[str]:
    errs = []
    if not d.get("body"):
        errs.append("'body' is required and must be non-empty")
    return errs


def _intelligence_brief(db: Session, intelligence_record_ids: list[str]) -> list[dict]:
    if not intelligence_record_ids:
        return []
    rows = db.query(mi.IntelligenceRecord).filter(mi.IntelligenceRecord.id.in_(intelligence_record_ids)).all()
    return [{"id": r.id, "kind": r.kind, "statement": r.statement, "confidence": r.confidence} for r in rows]


def generate_content(
    db: Session,
    kind: str,                       # "email" | "brief" | "meeting_prep"
    agent_name: str,                 # "email_personalisation" | "executive_briefing"
    system_prompt: str,
    role_template: str,              # developer-prompt guidance specific to the target role/channel
    person_id: str | None,
    org_id: str | None,
    intelligence_record_ids: list[str],
    banned_leaks: list[str] | None = None,
) -> mx.AiGeneration:
    person = db.get(models.Person, person_id) if person_id else None
    org = db.get(models.Organization, org_id) if org_id else None
    brief = _intelligence_brief(db, intelligence_record_ids)
    anonymized = ai_gen._anonymize(person, org, {"segment": "KSA banking"})

    developer_prompt = (
        f"{role_template}\n\nReturn ONLY JSON matching: {json.dumps(JSON_SCHEMA)}. "
        "cited_evidence_refs must list the intelligence_record ids (from the brief below) "
        "that the body actually draws on — if the brief is empty, return an empty list "
        "and write generic-but-safe content, do not fabricate specifics."
    )
    user_prompt = json.dumps({"contact_context": anonymized, "intelligence_brief": brief})

    req = orch.AgentRequest(
        tier=TIER, agent_name=agent_name,
        system_prompt=system_prompt, developer_prompt=developer_prompt,
        user_prompt=user_prompt, json_schema=JSON_SCHEMA,
        subject_type="person" if person_id else "organization",
        subject_id=person_id or org_id,
        validator=_validate,
    )
    result = orch.run_agent(db, req)

    if result.status != "ok":
        # Degrade to the existing offline path rather than writing nothing —
        # ai_gen.generate() already has a safe deterministic fallback template.
        gen = ai_gen.generate(db, kind, person_id=person_id, org_id=org_id,
                              context={"signal_title": brief[0]["statement"] if brief else None},
                              banned_leaks=banned_leaks)
        return gen

    o = result.output
    body = o.get("body", "")
    subject = o.get("subject", "")
    cited = o.get("cited_evidence_refs", [])

    qc = ai_gen.qc_check(body, banned_leaks)
    if brief and not cited:
        qc["passed"] = False
        qc.setdefault("issues", []).append("ungrounded: intelligence context was available but nothing was cited")

    status = "qc_passed" if qc["passed"] else "qc_failed"
    needs_human = bool(person and (person.seniority_level or "") == "c_suite")
    if qc["passed"] and needs_human:
        qc["issues"] = qc.get("issues", []) + ["c_suite: human approval required"]

    gen = mx.AiGeneration(
        kind=kind, person_id=person_id, org_id=org_id,
        input_context={**anonymized, "subject": subject, "cited_evidence_refs": cited,
                       "llm_call_id": result.llm_call_id, "trace_id": result.trace_id},
        output=body, qc=qc, status=status, model=result.model_used,
    )
    db.add(gen); db.commit()
    return gen
