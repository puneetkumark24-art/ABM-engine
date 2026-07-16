"""Module 10 — AI Personalization Engine.
AIP-001: PII is anonymized before any model call (placeholders in, personalize
locally after). AIP-002: QC must pass before a generation is send-eligible.
AIP-003: c-suite content always requires human approval.
The default generator is offline/deterministic (no API key needed); a Gemini
adapter can be registered later behind the same generate() interface."""
from __future__ import annotations
import re
from sqlalchemy.orm import Session
import models
import models_ext as mx

# pluggable model adapter: fn(kind, anonymized_context) -> text
_MODEL_ADAPTER = None


def register_model(fn) -> None:
    global _MODEL_ADAPTER
    _MODEL_ADAPTER = fn


def _offline_template(kind: str, ctx: dict) -> str:
    if kind == "subject":
        return f"A note on {ctx.get('signal_title', 'your digital initiatives')}"
    return (
        f"Dear {{name}},\n\n"
        f"I noticed {ctx.get('signal_title', 'your institution’s recent digital initiative')} — "
        f"relevant to what we see across {ctx.get('segment', 'KSA banking')}.\n\n"
        f"Decimal Technologies has helped institutions launch "
        f"{ctx.get('product', 'digital lending')} platforms in months, not years. "
        f"Would a short conversation be useful?\n\nBest regards,\n{{sender}}"
    )


def _anonymize(person: "models.Person | None", org: "models.Organization | None", extra: dict) -> dict:
    """AIP-001 — strip real PII; the model only ever sees placeholders."""
    ctx = dict(extra or {})
    ctx.pop("email", None); ctx.pop("phone", None)
    if person is not None:
        ctx["role"] = person.current_title or "executive"
        ctx["seniority"] = person.seniority_level or "senior"
    if org is not None:
        ctx["segment"] = "KSA banking"     # never the org's real name to the model
    return ctx


BANNED_LEAKS_DEFAULT = ["10 million", "65,000", "1,500 daily"]   # teaser-discipline examples


def qc_check(text: str, banned_leaks: list[str] | None = None) -> dict:
    """AIP-002 — rule-based QC: unresolved placeholders other than the allowed
    merge tags, banned leaked facts, length sanity."""
    issues = []
    allowed = {"{name}", "{sender}", "{institution}", "{role}"}
    for ph in set(re.findall(r"\{[a-z_]+\}", text or "")):
        if ph not in allowed:
            issues.append(f"unresolved placeholder {ph}")
    for leak in (banned_leaks if banned_leaks is not None else BANNED_LEAKS_DEFAULT):
        if leak.lower() in (text or "").lower():
            issues.append(f"teaser-discipline leak: '{leak}'")
    if len(text or "") < 40:
        issues.append("too short")
    if len(text or "") > 4000:
        issues.append("too long")
    return {"passed": not issues, "issues": issues}


def generate(db: Session, kind: str, person_id: str | None = None, org_id: str | None = None,
             context: dict | None = None, banned_leaks: list[str] | None = None) -> mx.AiGeneration:
    person = db.get(models.Person, person_id) if person_id else None
    org = db.get(models.Organization, org_id) if org_id else None
    ctx = _anonymize(person, org, context or {})

    fn = _MODEL_ADAPTER or _offline_template
    text = fn(kind, ctx)

    qc = qc_check(text, banned_leaks)
    status = "qc_passed" if qc["passed"] else "qc_failed"
    # AIP-003: c-suite always needs a human even when QC passes
    needs_human = bool(person and (person.seniority_level or "") == "c_suite")
    if qc["passed"] and needs_human:
        qc["issues"] = ["c_suite: human approval required"]

    gen = mx.AiGeneration(kind=kind, person_id=person_id, org_id=org_id,
                          input_context=ctx, output=text, qc=qc, status=status,
                          model="adapter" if _MODEL_ADAPTER else "offline-template")
    db.add(gen); db.commit()
    return gen


def approve(db: Session, generation_id: str) -> mx.AiGeneration:
    g = db.get(mx.AiGeneration, generation_id)
    if g and g.status == "qc_passed":
        g.status = "approved"; db.commit()
    return g
