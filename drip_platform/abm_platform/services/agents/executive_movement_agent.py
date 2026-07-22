"""
executive_movement_agent.py — Tier A agent (AI_Intelligence_Layer_Architecture.md
section 5.3): extracts structured leadership-change facts (who moved, from
what role to what role, at which organization, when) from a raw signal's
text. Runs after signal_classification_agent has already tagged
signal_type="leadership_change" — this agent is deliberately narrow (one
job: structured extraction) rather than re-deciding whether the signal IS a
leadership change.

Per Phase 6 of the architecture ("the AI should infer, not just extract"),
this agent also proposes WHY the move matters commercially — e.g. a new CIO
is a buying-committee reset, a promoted CFO with fintech background may be
receptive to digital-lending ROI framing — as a `commercial_implication`
field. That inference is advisory text for a human/Tier-B agent to read,
never auto-applied to a Person or Opportunity record.

Like signal_classification_agent, this agent never writes to the database.
It also NEVER auto-creates or auto-edits a Person row — matching AIP-003
(c-suite-sensitive data needs a human look) already enforced in ai_gen.py.
Callers get a `matched_person_hint` (name + org as extracted) for the UI to
offer as a suggested match against existing models.Person rows; confirming
the match is a human action.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from abm_platform.services import ai_orchestrator as orch

TIER = "A"
AGENT_NAME = "executive_movement"

SYSTEM_PROMPT = (
    "You extract structured leadership-change facts from banking-sector news "
    "text for Decimal Technologies, a B2B digital-lending/core-banking vendor "
    "selling into Saudi banks. You NEVER invent a name, title, or date not "
    "present in the text. If a fact isn't stated, leave that field empty "
    "rather than guessing."
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "person_name": {"type": "string"},
        "organization_name": {"type": "string"},
        "new_title": {"type": "string"},
        "previous_title": {"type": "string"},
        "previous_organization": {"type": "string"},
        "effective_date_text": {"type": "string"},   # as stated in the text, not normalized — normalization is a UI concern
        "is_incoming": {"type": "boolean"},           # true if this person is JOINING the org; false if departing
        "seniority_level": {"type": "string", "enum": ["c_suite", "svp_evp", "vp", "director", "manager", "unknown"]},
        "commercial_implication": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["person_name", "organization_name", "confidence"],
}

DEVELOPER_PROMPT = (
    "Extract the leadership-change fact from the text below. Return ONLY JSON "
    f"matching: {json.dumps(JSON_SCHEMA)}. commercial_implication should be one "
    "or two sentences on what this move might mean for a vendor selling core "
    "banking / digital lending / payments software into this account — e.g. "
    "buying-committee reset, receptiveness to a specific pitch angle — "
    "grounded ONLY in what the text and role imply, not invented biography."
)


@dataclass
class ExecutiveMovement:
    person_name: str | None
    organization_name: str | None
    new_title: str | None
    previous_title: str | None
    previous_organization: str | None
    effective_date_text: str | None
    is_incoming: bool | None
    seniority_level: str | None
    commercial_implication: str | None
    confidence: float
    status: str
    matched_person_hint: dict | None = None


def _validate(d: dict) -> list[str]:
    errs = []
    if not d.get("person_name"):
        errs.append("person_name is required and must be non-empty")
    if not d.get("organization_name"):
        errs.append("organization_name is required and must be non-empty")
    return errs


def extract(db: Session, signal_title: str, signal_summary: str, org_hint: str | None = None,
            subject_id: str | None = None) -> ExecutiveMovement:
    text = f"title: {signal_title}\nsummary: {signal_summary}"
    if org_hint:
        text += f"\nknown organization context: {org_hint}"

    req = orch.AgentRequest(
        tier=TIER, agent_name=AGENT_NAME,
        system_prompt=SYSTEM_PROMPT,
        developer_prompt=DEVELOPER_PROMPT,
        user_prompt=text,
        json_schema=JSON_SCHEMA,
        subject_type="signal",
        subject_id=subject_id,
        validator=_validate,
    )
    result = orch.run_agent(db, req)

    if result.status != "ok":
        return ExecutiveMovement(
            person_name=None, organization_name=None, new_title=None,
            previous_title=None, previous_organization=None, effective_date_text=None,
            is_incoming=None, seniority_level=None, commercial_implication=None,
            confidence=0.0, status=result.status,
        )

    o = result.output
    hint = {"name": o.get("person_name"), "organization": o.get("organization_name")}
    return ExecutiveMovement(
        person_name=o.get("person_name"),
        organization_name=o.get("organization_name"),
        new_title=o.get("new_title"),
        previous_title=o.get("previous_title"),
        previous_organization=o.get("previous_organization"),
        effective_date_text=o.get("effective_date_text"),
        is_incoming=o.get("is_incoming"),
        seniority_level=o.get("seniority_level"),
        commercial_implication=o.get("commercial_implication"),
        confidence=result.confidence,
        status="ok",
        matched_person_hint=hint,
    )
