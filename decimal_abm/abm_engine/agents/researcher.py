"""
abm_engine/agents/researcher.py
────────────────────────────────
Uses Claude with web_search tool to find the freshest signal
for each contact before writing their outreach message.
This is what replaces Clay's signal detection.
"""
from __future__ import annotations
import json
from datetime import datetime
from loguru import logger
import anthropic

from ..core.models import Contact, ResearchResult


SYSTEM_PROMPT = """\
You are a senior B2B sales intelligence analyst at Decimal Technologies.

Decimal Technologies is a B2B fintech infrastructure company headquartered in India,
expanding into the GCC (Saudi Arabia, UAE, Qatar, Kuwait, Oman).

Decimal's products:
- API-first digital account opening (retail + SME + corporate)
- AI-powered credit decisioning and digital lending
- Open banking infrastructure and API marketplace (1,200+ APIs)
- No-code banking product configurator (go-live in weeks, not months)
- SAMA/CBUAE regulatory compliance modules

Your job: research a specific banking executive and their institution.
Find the FRESHEST, most specific business signal that Decimal can use to
open a conversation. Think: new product launches, regulatory responses,
hiring signals, partnership announcements, technology investments.

Always return a JSON object — no prose, no markdown, just valid JSON.
"""


RESEARCH_PROMPT = """\
Research this contact and their institution. Find the most relevant, recent signal
that Decimal Technologies can use as an outreach hook.

Contact:
- Name: {full_name}
- Role: {role}
- Institution: {institution}
- Country: {country}
- Known signal (may be outdated): {key_signal}
- Decimal product fit: {product_fit}

Search for:
1. Recent news about {institution} in the last 6 months
2. Any regulatory announcements (SAMA, CBUAE) affecting {institution}
3. Any technology or digital banking investments by {institution}
4. Any LinkedIn activity or public statements by {full_name}

Return ONLY this JSON (no other text):
{{
  "fresh_signals": [
    "Signal 1 — specific and recent",
    "Signal 2 — specific and recent",
    "Signal 3 — specific and recent"
  ],
  "recommended_hook": "The single best signal to use as the email/DM opener",
  "context_summary": "2–3 sentence background on the account and why Decimal fits right now"
}}
"""


class ResearchAgent:
    """
    Calls Claude with web_search to get fresh account intelligence.
    Results are cached in DB — won't re-research the same contact
    within 7 days unless forced.
    """

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = "claude-sonnet-4-6"

    def research_contact(self, contact: Contact) -> ResearchResult:
        logger.info(
            "Researching {} @ {} (touch {}/5)",
            contact.full_name, contact.institution, contact.current_touch + 1
        )

        prompt = RESEARCH_PROMPT.format(
            full_name    = contact.full_name,
            role         = contact.role,
            institution  = contact.institution,
            country      = contact.country,
            key_signal   = contact.key_signal,
            product_fit  = contact.product_fit,
        )

        try:
            response = self.client.messages.create(
                model     = self.model,
                max_tokens= 1024,
                system    = SYSTEM_PROMPT,
                tools     = [{"type": "web_search_20250305", "name": "web_search"}],
                messages  = [{"role": "user", "content": prompt}]
            )

            # Extract the text block from the response
            result_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    result_text += block.text

            # Parse JSON
            data = json.loads(result_text)

            return ResearchResult(
                contact_id       = contact.id,
                contact_name     = contact.full_name,
                institution      = contact.institution,
                fresh_signals    = data.get("fresh_signals", [contact.key_signal]),
                recommended_hook = data.get("recommended_hook", contact.key_signal),
                context_summary  = data.get("context_summary", ""),
                researched_at    = datetime.utcnow(),
            )

        except json.JSONDecodeError as e:
            logger.warning(
                "JSON parse failed for {} — using fallback signal. Error: {}",
                contact.full_name, e
            )
            return ResearchResult(
                contact_id       = contact.id,
                contact_name     = contact.full_name,
                institution      = contact.institution,
                fresh_signals    = [contact.key_signal],
                recommended_hook = contact.key_signal,
                context_summary  = contact.outreach_angle,
                researched_at    = datetime.utcnow(),
            )

        except Exception as e:
            logger.error("Research failed for {}: {}", contact.full_name, e)
            # Graceful fallback — don't crash the engine
            return ResearchResult(
                contact_id       = contact.id,
                contact_name     = contact.full_name,
                institution      = contact.institution,
                fresh_signals    = [contact.key_signal],
                recommended_hook = contact.key_signal,
                context_summary  = contact.outreach_angle,
                researched_at    = datetime.utcnow(),
            )
