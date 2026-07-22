"""
email_personalisation_agent.py — Tier C agent (AI_Intelligence_Layer_Architecture.md
section 5.5): generates channel-ready email copy grounded in Tier B's
intelligence_record output. See tier_c_common.py for the shared
orchestrator-call/QC/human-gate implementation both Tier C agents use.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models_ext as mx
from abm_platform.services.agents import tier_c_common as common

AGENT_NAME = "email_personalisation"

SYSTEM_PROMPT = (
    "You write on-brand cold/warm outreach email copy for Decimal Technologies, "
    "a B2B digital-lending/core-banking platform vendor selling into Saudi banks. "
    "You NEVER invent facts not present in the provided intelligence brief. You "
    "follow teaser discipline: reference that Decimal has relevant proof points "
    "without leaking specific proprietary numbers that should stay behind a "
    "meeting. You never write anything for a c-suite contact that oversells or "
    "presumes familiarity — keep it concise and respectful of seniority."
)

ROLE_TEMPLATE = (
    "Write a single outreach email: a short subject line and a body of 3-5 "
    "short paragraphs, ending with a low-friction call to action (a short call, "
    "not a large ask). Ground the opening line in the intelligence brief's "
    "most relevant, highest-confidence item if one exists."
)


def generate(db: Session, person_id: str | None, org_id: str | None,
             intelligence_record_ids: list[str] | None = None,
             banned_leaks: list[str] | None = None) -> mx.AiGeneration:
    return common.generate_content(
        db, kind="email", agent_name=AGENT_NAME,
        system_prompt=SYSTEM_PROMPT, role_template=ROLE_TEMPLATE,
        person_id=person_id, org_id=org_id,
        intelligence_record_ids=intelligence_record_ids or [],
        banned_leaks=banned_leaks,
    )
