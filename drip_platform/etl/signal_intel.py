"""
signal_intel.py — SIG-PARTNER classification layer (ABM Business Logic Bible,
OPEN-GAP-SIG-06).

Per the Bible: this is deliberately NOT a new signal source. A partnership
announcement already arrives as a normal signal (news, manual entry, whatever
sourced it) — what's missing is the interpretation layer that tells you
whether "Bank X signs deal with Vendor Y" is good news or bad news for
Decimal. A bank partnering with Backbase is a competitive-closure signal
(their vendor evaluation may be closing, act urgently or reassess).
The same bank partnering with Tarabut is an integration opportunity
(open banking middleware Decimal can sit alongside). Partnering with SAMA-
or Fintech-Saudi-adjacent bodies is a compliance-alignment signal, different
in kind from either. Without this layer, all three look like identical
generic "news" to the dashboard.

The vendor registry below is system-wide config (not per-bank, per the
Bible), and deliberately simple: case-insensitive substring matching against
a curated list, not NLP/AI classification. If a signal's title or summary
names a known competitor, the classifier flags COMPETITIVE_CLOSURE; a known
complementary player flags INTEGRATION_OPPORTUNITY; a regulator/ecosystem
body flags COMPLIANCE_ALIGNMENT; a known neutral advisor flags NEUTRAL. This
is a suggestion for a human to confirm on the signal form, not an
auto-committed fact — the matched vendor name is always shown alongside the
classification so it's obvious why the classifier said what it said, and it
can be overridden freely.
"""
from __future__ import annotations
import re

# Named in the Bible's SIG-VENDOR / SIG-PARTNER sections as core banking / digital banking
# platform vendors that compete directly with Decimal's product portfolio. A bank naming one
# of these in a partnership/MOU announcement is the single highest-urgency negative signal
# the engine can produce — the vendor evaluation this account was in may be closing.
COMPETITOR_VENDORS = [
    "backbase", "temenos", "fis global", "fis", "finastra", "mambu",
    "thought machine", "oracle flexcube", "flexcube", "infosys finacle", "finacle",
    "sap banking", "sopra banking", "sopra", "ncr", "avaloq",
]

# Complementary players — open banking middleware, payment processors, connectivity/BNPL —
# named in the Bible as INTEGRATION_OPPORTUNITY territory: Decimal can sit alongside these,
# not lose to them.
COMPLEMENTARY_VENDORS = [
    "tarabut", "geidea", "lean technologies", "lean tech", "hyperpay", "tamara", "tabby",
    "mastercard", "visa", "checkout.com", "stripe", "paytabs", "moyasar",
]

# Neutral / advisory — consulting or infrastructure names that show up constantly in bank
# announcements but carry no competitive signal either way (per the Bible: "KPMG=neutral/advisor").
NEUTRAL_ADVISORS = [
    "kpmg", "deloitte", "ey", "ernst & young", "pwc", "mckinsey", "bcg", "accenture",
    "aws", "amazon web services", "microsoft azure", "google cloud",
]

# Regulator / ecosystem-orchestrator bodies — a partnership or MOU naming one of these is a
# COMPLIANCE_ALIGNMENT signal, a different kind of "strategic commitment" than a vendor deal.
REGULATORY_ADJACENT = [
    "sama", "saudi central bank", "cma", "capital market authority",
    "fintech saudi", "etimad",
]

CLASSIFICATION_LABELS = {
    "COMPETITIVE_CLOSURE": "Competitive closure — a competitor may be winning this account",
    "INTEGRATION_OPPORTUNITY": "Integration opportunity — complementary player, not a threat",
    "COMPLIANCE_ALIGNMENT": "Compliance alignment — regulator/ecosystem-body partnership",
    "NEUTRAL": "Neutral — advisory/infrastructure partner, no competitive signal",
}


def _find_match(text_lower: str, registry: list[str]) -> str | None:
    for name in registry:
        # \b word-boundary matching so "fis" doesn't match inside "satisfies", etc.
        if re.search(r"\b" + re.escape(name) + r"\b", text_lower):
            return name
    return None


def classify_partnership(title: str | None, summary: str | None) -> dict:
    """Returns {classification, matched_vendor} — classification is one of the four keys in
    CLASSIFICATION_LABELS, or None if nothing in the registry was recognized (an
    UNCLASSIFIED partnership signal — still worth logging, just needs a human to name what
    it is). Priority order when multiple registries match in the same text: a competitor
    mention always wins (the most urgent interpretation shouldn't be masked by an incidental
    advisor mention in the same announcement), then regulatory, then complementary, then
    neutral."""
    text_lower = f"{title or ''} {summary or ''}".lower()
    if not text_lower.strip():
        return {"classification": None, "matched_vendor": None}

    competitor = _find_match(text_lower, COMPETITOR_VENDORS)
    if competitor:
        return {"classification": "COMPETITIVE_CLOSURE", "matched_vendor": competitor}

    regulatory = _find_match(text_lower, REGULATORY_ADJACENT)
    if regulatory:
        return {"classification": "COMPLIANCE_ALIGNMENT", "matched_vendor": regulatory}

    complementary = _find_match(text_lower, COMPLEMENTARY_VENDORS)
    if complementary:
        return {"classification": "INTEGRATION_OPPORTUNITY", "matched_vendor": complementary}

    neutral = _find_match(text_lower, NEUTRAL_ADVISORS)
    if neutral:
        return {"classification": "NEUTRAL", "matched_vendor": neutral}

    return {"classification": None, "matched_vendor": None}
