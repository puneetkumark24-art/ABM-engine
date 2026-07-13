"""
abm_engine/agents/writer.py
────────────────────────────
Layer 4+5: Buying committee persona routing + bilingual message generation.

Key upgrades from v1:
- 5 distinct persona prompts: CTO, CDO, CEO, HEAD_RETAIL, CISO
- Arabic + English for KSA national senior contacts
- Warm relationship = modified opener (not cold)
- FI track = different hooks and angles than bank track
- 4-touch email cadence (matches Layer 5 doc) + LinkedIn 3-step trigger-based
"""
from __future__ import annotations
from datetime import datetime
from loguru import logger
import anthropic

from ..core.models import Contact, ResearchResult, GeneratedMessage, TouchType, Language


# ─── System prompt ────────────────────────────────────────────────────────────

WRITER_SYSTEM = """\
You are a senior GTM executive at Decimal Technologies.

About Decimal Technologies:
- B2B fintech infrastructure for banks and financial institutions in GCC
- API-first digital account opening (retail, SME, corporate)
- AI-powered credit decisioning and digital lending
- Open banking infrastructure — 1,200+ pre-built banking APIs
- No-code product configurator — new products live in weeks, not months
- SAMA and CBUAE compliance modules built in
- Proven deployments: Kotak 811, AU Small Finance Bank, Yes Bank, HDFC Bank (India)
- First mover in GCC — currently onboarding anchor clients

NON-NEGOTIABLE writing rules:
1. Open with a specific, real signal about their institution or role — never generic
2. NEVER: "I hope this email finds you well", "I am reaching out", "leverage", "synergy", "robust", "seamless"
3. Emails: max 100 words body. Subject: specific, no clickbait
4. LinkedIn connection note: HARD limit 280 characters. Count every character.
5. LinkedIn DM: max 150 words. Conversational, not a pitch document.
6. One soft CTA at the end. Never more than one ask.
7. Tone: smart peer, not salesperson. Sound like someone who knows their industry.
8. Output ONLY the message. No preamble, no explanation, no "Here is the email:".
9. For warm relationships: open referencing the prior connection, not as cold outreach.
"""


# ─── Persona pain points (Layer 4) ───────────────────────────────────────────

PERSONA_PAIN = {
    "CTO": {
        "pain":  "Legacy core banking slowing digital product delivery. API sprawl. Time-to-market = months not weeks.",
        "angle": "Most bank CTOs say their biggest bottleneck isn't talent — it's the API layer between intent and execution.",
        "proof": "We helped a top-5 Indian bank cut digital account opening from 7 days to 4 minutes. Same stack, no core banking replacement.",
    },
    "CDO": {
        "pain":  "Pressure to ship BNPL, instant account opening, while IT says 6+ months per feature.",
        "angle": "The CDOs we work with say the gap is always the same: digital ambition vs delivery speed.",
        "proof": "Kotak 811 launched 3 new digital products in one quarter using Decimal's no-code configurator.",
    },
    "CEO": {
        "pain":  "Competitive pressure from digital banks. Vision 2030 mandates digital-first. Board pressure on digital revenue.",
        "angle": "With D360 and STC Bank now live, the window for digital retail positioning is compressing fast.",
        "proof": "Banks that moved on embedded finance infrastructure in 2024 are now setting the rails others run on.",
    },
    "HEAD_RETAIL": {
        "pain":  "Losing retail wallet share to fintechs. BNPL adoption accelerating among under-35s. High drop-off in digital onboarding.",
        "angle": "Saudi retail customers under 35 complete fintech account openings in under 4 minutes.",
        "proof": "We've helped banks cut digital onboarding time to under 3 minutes — driving 40-60% drop-off reduction.",
    },
    "CISO": {
        "pain":  "SAMA open banking mandate requires external API exposure — new attack surface. Balancing compliance with security.",
        "angle": "SAMA Phase 2 effectively mandates external API access for all licensed banks — but most treat security as an afterthought.",
        "proof": "Decimal's API gateway has SAMA-compliant security controls built in — not bolted on after.",
    },
    "HEAD_PRODUCT": {
        "pain":  "Building core banking primitives in-house is slow and expensive. SAMA compliance adds complexity.",
        "angle": "Most fintech product heads at Series B/C wrestle with the same decision — build rails in-house or use a modular provider.",
        "proof": "The build path typically costs 12-18 months and SAR 8-15M in engineering.",
    },
    "HEAD_COMPLIANCE": {
        "pain":  "SAMA licensing requirements tightening — NAFATH integration, KYC/AML, open banking API security.",
        "angle": "SAMA consumer finance licensing has become significantly more complex since 2024.",
        "proof": "Decimal's compliance modules are pre-certified — reducing your SAMA audit surface, not expanding it.",
    },
    "OTHER": {
        "pain":  "Speed to market for new financial products.",
        "angle": "Banks and FIs using API-first infrastructure are shipping new products 3-4× faster.",
        "proof": "Decimal is deployed at 15+ financial institutions across India and expanding into GCC.",
    },
}


# ─── Email prompts per touch ──────────────────────────────────────────────────

def _email_prompt(contact: Contact, research: ResearchResult,
                  touch: int, warm: bool) -> str:
    persona = contact.persona.upper() if hasattr(contact.persona, "upper") else str(contact.persona).upper()
    pp      = PERSONA_PAIN.get(persona, PERSONA_PAIN["OTHER"])
    seg     = contact.segment or "COMMERCIAL"
    is_fi   = contact.institution_type.upper() in ("FI", "BNPL", "SME", "EMBEDDED", "PAYMENTS")

    warm_opener = "warm relationship" if warm else "cold outreach"
    fi_context  = "This is a non-bank financial institution (fintech/BNPL/SME lender) — faster decision cycle, smaller committee." if is_fi else "This is a regulated bank — longer cycle, relationship-first."

    touch_instructions = {
        1: f"""Touch 1 — Hyper-personalised opener.
Open with this exact signal: "{research.recommended_hook}"
One sentence on what Decimal does (from their pain angle, not generic).
Soft CTA: "Worth a 20-minute conversation?"
{"Since this is a WARM relationship, open acknowledging the prior connection." if warm else "Cold outreach — signal-led, no relationship reference."}
Max 90 words body.""",

        2: f"""Touch 2 — Value-led insight. No pitch, no reference to previous email.
Share one relevant benchmark: banks using API-first account opening reduce digital onboarding drop-off by 40-60%.
Connect to their pain: {pp["pain"]}
End with a question, not a CTA.
Max 90 words body.""",

        3: f"""Touch 3 — Comparable customer proof.
Reference this proof point: {pp["proof"]}
2 sentences on the result. Then: "Happy to share a quick analysis relevant to [{contact.institution}]'s situation."
Short CTA.
Max 90 words body.""",

        4: f"""Touch 4 — Breakup / low-friction close.
"If the timing isn't right, no problem — happy to reconnect when it makes sense."
If open banking infrastructure is on their radar for H2, even a 15-minute call is worth it.
This is the highest-reply touch — keep it human and gracious.
Max 70 words body.""",
    }

    return f"""
Persona pain: {pp["pain"]}
Persona angle: {pp["angle"]}
Contact: {contact.display_name}, {contact.role} ({persona}) at {contact.institution} ({contact.country})
Segment: {seg} | {fi_context}
Outreach type: {warm_opener}
Signal / context: {research.context_summary}

{touch_instructions.get(touch, touch_instructions[1])}

Format:
Subject: [specific, one line]

[Body]
"""


# ─── LinkedIn prompts ──────────────────────────────────────────────────────────

def _linkedin_prompt(contact: Contact, research: ResearchResult,
                     touch: int, warm: bool) -> str:
    persona = contact.persona.upper() if hasattr(contact.persona, "upper") else "OTHER"
    pp      = PERSONA_PAIN.get(persona, PERSONA_PAIN["OTHER"])

    if touch == 1:
        return f"""Write a LinkedIn CONNECTION REQUEST NOTE.
HARD LIMIT: 280 characters including spaces. Count carefully.

Contact: {contact.display_name}, {contact.role} at {contact.institution}
Signal: {research.recommended_hook}

Rules:
- Do NOT mention Decimal
- Reference something specific about their company or the signal
- End naturally — no CTA, no ask
- Sound like a peer, not a recruiter

Output ONLY the note text. Nothing else."""

    if touch == 2:
        return f"""Write a LinkedIn DM — sent after connection accepted (or as follow-up).
Max 150 words.

Contact: {contact.display_name}, {contact.role} at {contact.institution}
Signal: {research.recommended_hook}
Their pain: {pp["pain"]}

Now you can briefly mention Decimal (1 sentence max).
Offer something of value: "Happy to share a quick analysis on SAMA open banking readiness across KSA banks."
End with a soft question.

Output ONLY the message."""

    if touch == 3:
        return f"""Write a LinkedIn DM — follow-up, no reply to DM 2.
Max 120 words.

Contact: {contact.display_name}, {contact.role} at {contact.institution}
Reference their institution's recent context: {research.context_summary}
Share one insight relevant to their role.
No hard pitch.

Output ONLY the message."""

    return f"""Write a final LinkedIn DM — gracious exit.
Max 70 words.
Contact: {contact.display_name}, {contact.role} at {contact.institution}
Brief, human, leaves the door open.
Output ONLY the message."""


# ─── Arabic prompt wrapper ────────────────────────────────────────────────────

def _arabic_prompt(english_message: str, contact: Contact) -> str:
    return f"""Translate and culturally adapt the following business outreach message into formal Modern Standard Arabic (فصحى) suitable for senior banking executives in Saudi Arabia.

Rules:
- Use formal MSA — no dialects, no colloquialisms
- Maintain professional banking register
- Keep the same structure: subject line (if email) + body
- Preserve all specific numbers, company names, and facts
- Arabic greeting: appropriate business greeting, not literal translation
- Do NOT add extra sentences or change the meaning

Contact: {contact.full_name}, {contact.institution}

Original message:
{english_message}

Output ONLY the Arabic translation."""


# ─── Writer Agent ─────────────────────────────────────────────────────────────

class WriterAgent:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = "claude-sonnet-4-6"

    def _call(self, prompt: str, max_tokens: int = 512) -> str:
        response = self.client.messages.create(
            model      = self.model,
            max_tokens = max_tokens,
            system     = WRITER_SYSTEM,
            messages   = [{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()

    def _parse_email(self, raw: str) -> tuple[str, str]:
        """Split subject and body from Claude output."""
        lines   = raw.strip().split("\n")
        subject = ""
        body    = raw
        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                body    = "\n".join(lines[i+1:]).strip()
                break
        return subject, body

    def generate_email(self, contact: Contact, research: ResearchResult,
                       touch: int) -> GeneratedMessage:
        warm   = contact.has_warm_relationship
        prompt = _email_prompt(contact, research, touch, warm)
        raw    = self._call(prompt)

        subject, body = self._parse_email(raw)
        body_ar = None

        # Generate Arabic for KSA national senior contacts on T1 and T4
        if contact.needs_arabic and touch in (1, 4):
            try:
                ar_prompt = _arabic_prompt(f"Subject: {subject}\n\n{body}", contact)
                body_ar   = self._call(ar_prompt, max_tokens=768)
                logger.info("Arabic email generated for {} (touch {})", contact.full_name, touch)
            except Exception as e:
                logger.warning("Arabic generation failed for {}: {}", contact.full_name, e)

        logger.info("Email T{} → {} | subject: {}", touch, contact.full_name, subject[:50])
        return GeneratedMessage(
            contact_id   = contact.id,
            touch_number = touch,
            touch_type   = TouchType.EMAIL,
            language     = Language.EN,
            subject      = subject,
            body         = body,
            hook_used    = research.recommended_hook,
            word_count   = len(body.split()),
        )

    def generate_linkedin_dm(self, contact: Contact, research: ResearchResult,
                             touch: int) -> GeneratedMessage:
        warm   = contact.has_warm_relationship
        prompt = _linkedin_prompt(contact, research, touch, warm)
        body   = self._call(prompt, max_tokens=400)

        # Enforce 280 char limit on connection note
        if touch == 1 and len(body) > 280:
            logger.warning("LinkedIn note too long ({} chars) for {} — truncating",
                           len(body), contact.full_name)
            body = body[:277] + "..."

        # Arabic for KSA nationals on connection note (touch 1)
        body_ar = None
        if contact.needs_arabic and touch == 1:
            try:
                ar_prompt = _arabic_prompt(body, contact)
                body_ar   = self._call(ar_prompt, max_tokens=400)
            except Exception as e:
                logger.warning("Arabic LinkedIn failed for {}: {}", contact.full_name, e)

        logger.info("LinkedIn T{} → {} ({} chars)", touch, contact.full_name, len(body))
        return GeneratedMessage(
            contact_id   = contact.id,
            touch_number = touch,
            touch_type   = TouchType.LINKEDIN,
            language     = Language.EN,
            subject      = None,
            body         = body,
            hook_used    = research.recommended_hook,
            word_count   = len(body.split()),
        )
