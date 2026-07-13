"""
abm_engine/scoring/engine.py
─────────────────────────────
Layer 3: 4-dimension weighted scoring model.

Runs weekly (and after every new P1 signal).
Updates every contact's composite_score and tier.
Saves a breakdown for full auditability.

Dimensions:
  Signal Strength      35pts — recency, count, P1/P2 weighting
  Regulatory Pressure  30pts — SAMA deadline proximity, greenfield, segment
  Persona Reachability 20pts — verified email + LinkedIn URL
  Existing Relationship 15pts — warm contact flag, previous meetings

Thresholds: HOT ≥75 | WARM 50–74 | COLD <50
"""
from __future__ import annotations
from datetime import datetime, timedelta
from loguru import logger

from ..database.db import (
    get_contacts_for_scoring, get_signals_for_institution,
    update_contact_score, save_score_breakdown,
    update_account_score,
)


# ─── Tier thresholds (matches Layer 3 doc exactly) ────────────────────────────
HOT_THRESHOLD  = 75
WARM_THRESHOLD = 50


def _tier(score: int) -> str:
    if score >= HOT_THRESHOLD:
        return "HOT"
    if score >= WARM_THRESHOLD:
        return "WARM"
    return "COLD"


# ─── Dimension 1: Signal Strength (max 35) ────────────────────────────────────

def score_signal_strength(institution: str) -> int:
    """
    Recency + volume + priority weighting.
    P1 signals score 2× a P2 signal.
    Signals in last 30 days score full; older signals decay.
    """
    signals = get_signals_for_institution(institution, days=60)
    if not signals:
        return 0

    now   = datetime.utcnow()
    score = 0

    for sig in signals:
        detected = datetime.fromisoformat(sig["detected_at"].replace("Z", ""))
        age_days  = (now - detected).days

        # Recency multiplier: full points within 30 days, half at 31-60
        recency = 1.0 if age_days <= 30 else 0.5

        # Priority weight
        if sig["priority"] == "P1":
            base = 14   # P1 = 2× P2
        elif sig["priority"] == "P2":
            base = 7
        else:
            base = 3    # P3

        score += int(base * recency)

    # Cap at max 35
    return min(score, 35)


# ─── Dimension 2: Regulatory Pressure (max 30) ────────────────────────────────

# SAMA deadline proximity by segment (points 0–30)
SEGMENT_PRESSURE = {
    "DIGITAL":    30,   # newly licensed digital banks — maximum pressure
    "BNPL":       28,   # consumer finance licensing tightening
    "SME":        25,   # SAMA SME financing regulations
    "EMBEDDED":   24,
    "ISLAMIC":    20,   # SAMA open banking affects all
    "COMMERCIAL": 18,
    "PAYMENTS":   22,
    "OTHER":      10,
}

def score_regulatory_pressure(contact: dict) -> int:
    """
    Segment-based SAMA pressure + greenfield bonus + FI vs bank factor.
    """
    segment      = (contact.get("segment") or "COMMERCIAL").upper()
    institution  = contact.get("institution", "")
    signals      = get_signals_for_institution(institution, days=30)

    base = SEGMENT_PRESSURE.get(segment, 10)

    # Greenfield boost: newly licensed bank has immediate infrastructure need
    if any(s["signal_type"] == "NEW_LICENSE" for s in signals):
        base = min(base + 10, 30)

    # Active SAMA signal for this account
    sama_signals = [s for s in signals if s["source_name"] == "SAMA"]
    if sama_signals:
        base = min(base + 5, 30)

    return min(base, 30)


# ─── Dimension 3: Persona Reachability (max 20) ───────────────────────────────

PERSONA_WEIGHTS = {
    "CTO":             20,   # most reachable for our product
    "CDO":             20,
    "HEAD_PRODUCT":    18,
    "CEO":             15,
    "HEAD_RETAIL":     14,
    "CISO":            12,
    "HEAD_COMPLIANCE": 12,
    "OTHER":           8,
}

def score_persona_reachability(contact: dict) -> int:
    """
    Verified email + LinkedIn URL = full points.
    Missing either = penalty.
    Senior personas score higher even with partial data.
    """
    persona          = (contact.get("persona") or "OTHER").upper()
    has_email        = bool(contact.get("email"))
    email_confidence = (contact.get("email_confidence") or "low").lower()
    has_linkedin     = bool(contact.get("linkedin_url"))

    persona_base = PERSONA_WEIGHTS.get(persona, 8)

    # Reachability factor based on data quality
    if has_email and email_confidence in ("high", "medium") and has_linkedin:
        factor = 1.0   # full score
    elif has_email and has_linkedin:
        factor = 0.85
    elif has_email or has_linkedin:
        factor = 0.6
    else:
        factor = 0.2   # no contact data — very low

    return min(int(persona_base * factor), 20)


# ─── Dimension 4: Existing Relationship (max 15) ─────────────────────────────

def score_existing_relationship(contact: dict) -> int:
    """
    Warm contact = full 15 points.
    HubSpot contact ID present = some history = 8 points.
    Cold = 0.
    """
    if contact.get("has_warm_relationship"):
        return 15
    if contact.get("hubspot_contact_id"):
        return 8
    return 0


# ─── Main Scoring Engine ──────────────────────────────────────────────────────

class ScoringEngine:
    """
    Scores every active contact.
    Run weekly via scheduler, or immediately after a P1 signal fires.
    """

    def run(self, force_all: bool = False) -> dict:
        """
        Score all active contacts.
        Returns summary: {updated, upgraded, downgraded}
        """
        logger.info("═══ Scoring Engine Started ═══")
        contacts  = get_contacts_for_scoring()
        updated   = 0
        upgraded  = 0
        downgraded = 0

        for contact in contacts:
            old_score = contact.get("priority_score", 0)
            old_tier  = contact.get("tier", "COLD")

            # Compute each dimension
            d1 = score_signal_strength(contact["institution"])
            d2 = score_regulatory_pressure(contact)
            d3 = score_persona_reachability(contact)
            d4 = score_existing_relationship(contact)

            new_score = d1 + d2 + d3 + d4
            new_tier  = _tier(new_score)

            # Save breakdown for auditability
            save_score_breakdown(
                contact_id            = contact["id"],
                institution           = contact["institution"],
                signal_strength       = d1,
                regulatory_pressure   = d2,
                persona_reachability  = d3,
                existing_relationship = d4,
                composite_score       = new_score,
                tier                  = new_tier,
            )

            # Update contact if score changed
            if new_score != old_score or new_tier != old_tier:
                update_contact_score(contact["id"], new_score, new_tier)
                updated += 1

                if new_tier == "HOT" and old_tier != "HOT":
                    upgraded += 1
                    logger.info(
                        "↑ UPGRADED to HOT: {} @ {} (score: {}→{})",
                        contact["full_name"], contact["institution"], old_score, new_score
                    )
                elif old_tier == "HOT" and new_tier != "HOT":
                    downgraded += 1
                    logger.info(
                        "↓ DOWNGRADED from HOT: {} @ {} (score: {}→{})",
                        contact["full_name"], contact["institution"], old_score, new_score
                    )

        summary = {"contacts_scored": len(contacts), "updated": updated,
                   "upgraded": upgraded, "downgraded": downgraded}
        logger.info("═══ Scoring Complete: {} ═══", summary)
        return summary

    def score_one(self, contact: dict) -> dict:
        """Score a single contact and return the breakdown."""
        d1 = score_signal_strength(contact["institution"])
        d2 = score_regulatory_pressure(contact)
        d3 = score_persona_reachability(contact)
        d4 = score_existing_relationship(contact)
        total = d1 + d2 + d3 + d4
        return {
            "signal_strength":       d1,
            "regulatory_pressure":   d2,
            "persona_reachability":  d3,
            "existing_relationship": d4,
            "composite_score":       total,
            "tier":                  _tier(total),
        }
