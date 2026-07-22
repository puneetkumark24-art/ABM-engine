"""
executive_briefing_agent.py — Tier C agent (AI_Intelligence_Layer_Architecture.md
section 5.6): formats Tier B's synthesized intelligence into a role-appropriate
brief. Same underlying intelligence_records, different template per role — an
AE call-prep brief and a sales-manager portfolio brief are two cheap
formatting calls over the same Tier B output, not two expensive reasoning
passes (the cost point 5.6 explicitly calls out).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models_ext as mx
from abm_platform.services.agents import tier_c_common as common

AGENT_NAME = "executive_briefing"

SYSTEM_PROMPT = (
    "You format banking-sector account intelligence into a role-appropriate "
    "internal brief for Decimal Technologies sales staff. You NEVER invent "
    "facts not present in the provided intelligence brief — if the brief is "
    "sparse, say so explicitly rather than padding with generic filler."
)

ROLE_TEMPLATES = {
    "meeting_prep": (
        "Write a pre-call brief for the Account Executive about to speak with "
        "this contact: who they are, the single most important why-now point, "
        "any risk flags to be aware of, and one suggested opening question. "
        "Keep it to what's useful in the 5 minutes before a call."
    ),
    "portfolio_review": (
        "Write a concise portfolio-review brief for a sales manager: account "
        "status, the top hypothesis driving this account's priority, and the "
        "single highest-value next-best-action if one exists. Written for "
        "someone scanning many accounts quickly, not one deep-dive."
    ),
}


def generate(db: Session, role: str, person_id: str | None, org_id: str | None,
             intelligence_record_ids: list[str] | None = None) -> mx.AiGeneration:
    role_template = ROLE_TEMPLATES.get(role, ROLE_TEMPLATES["meeting_prep"])
    kind = "brief" if role == "portfolio_review" else "meeting_prep"
    return common.generate_content(
        db, kind=kind, agent_name=AGENT_NAME,
        system_prompt=SYSTEM_PROMPT, role_template=role_template,
        person_id=person_id, org_id=org_id,
        intelligence_record_ids=intelligence_record_ids or [],
    )
