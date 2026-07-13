"""
signal_decay.py — Signal Pipeline P1: EPIS confidence/decay stamping on
existing (manually entered) signals. No new scraping, no raw_captures,
no source_registry yet — those are P2+ per
docs/Signal_Pipeline_Architecture.md §6. This is the "highest-leverage,
lowest-risk next build": everything already in `signals` gets a
confidence_score, decay_category, and decay_expires_at, and every future
save (manual or automated) gets stamped the same way.

Grounded directly in two prior docs in this project, not invented fresh:
  - docs/Signal_Pipeline_Architecture.md §4.1 (EPIS-RCM-01) — the four new
    columns (confidence_score, decay_category, decay_expires_at,
    source_reliability) and the instruction that decay_category is set
    automatically from signal_type via a lookup table, no new human input.
  - "Signal Source Bottleneck Analysis.md" §2.5 (EPIS-HALF-01, ENR-DECAY) —
    the four decay tiers and their day ranges (Operational 7-30d
    contact-level, Tactical 30-90d activity-level, Strategic 6-12mo
    priority-level, Structural 3-5y identity-level), and the explicit
    worked mapping "rfp/tender -> tactical, partnership -> strategic,
    hiring -> operational, regulatory -> strategic" that this module's
    SIGNAL_TYPE_TO_DECAY_CATEGORY extends to the other signal_types DRIP
    actually uses.

`source_reliability` (the fourth EPIS-RCM-01 column) is deliberately left
NULL by this module — it's populated from `source_registry` per §4.2 of the
architecture doc, which is a P2 table that doesn't exist yet. Nothing here
fabricates a reliability score in its absence (EPIS-RCM-05: "the engine
never fabricates confidence; absence of evidence is recorded, not filled
with an inferred value").
"""
from __future__ import annotations
from datetime import datetime, timedelta

# ── Decay tiers (Bottleneck Analysis §2.5, EPIS-HALF-01) ──────────────────
# Each category's day-count is the midpoint of the Bible's stated range,
# not the endpoint, so a signal doesn't flip to "decayed" the instant the
# range technically opens up.
DECAY_TIER_DAY_RANGES = {
    "OPERATIONAL": (7, 30),     # contact-level facts
    "TACTICAL": (30, 90),       # activity-level
    "STRATEGIC": (180, 365),    # priority-level (6-12mo)
    "STRUCTURAL": (1095, 1825),  # identity-level (3-5y)
}

DECAY_HALF_LIFE_DAYS = {
    category: (lo + hi) // 2
    for category, (lo, hi) in DECAY_TIER_DAY_RANGES.items()
}
# -> {"OPERATIONAL": 18, "TACTICAL": 60, "STRATEGIC": 272, "STRUCTURAL": 1460}

# ── signal_type -> decay_category ──────────────────────────────────────────
# The three explicit in the architecture doc/bottleneck analysis are
# rfp->tactical, partnership->strategic, hiring->operational, and
# regulatory->strategic (stated twice, verbatim, in both source docs).
# The remaining DRIP signal_types (dashboard/app.py SIGNAL_TYPES) are
# extended here using the same rationale the Bible applies to the named
# three: does this fact describe a contact-level/routine event
# (operational), a time-bound activity (tactical), a lasting priority-level
# shift (strategic), or a rarely-changing identity fact (structural, not
# currently auto-assigned since no DRIP signal_type is identity-level)?
SIGNAL_TYPE_TO_DECAY_CATEGORY = {
    "rfp": "TACTICAL",               # matters until the deadline passes, then goes historical
    "partnership": "STRATEGIC",      # a competitive-closure signal from months ago is still load-bearing
    "hiring": "OPERATIONAL",         # a single hire is a routine, fast-decaying fact
    "regulatory": "STRATEGIC",       # a regulatory shift changes priority for a long window
    "leadership_change": "STRATEGIC",  # relationship-map impact persists like a partnership does
    "product_launch": "TACTICAL",    # time-bound competitive/positioning window
    "funding": "STRATEGIC",          # a capital event has lasting strategic relevance
    "expansion": "TACTICAL",         # activity-level, similar half-life to a product launch
    "earnings": "TACTICAL",          # relevant roughly until the next quarter's disclosure
    "other": "OPERATIONAL",          # unclassified catch-all: shortest decay by default (EDGE-EPIS-01
                                      # spirit — don't let un-taxonomized evidence linger overweighted)
}

DEFAULT_DECAY_CATEGORY = "OPERATIONAL"


def decay_category_for_signal_type(signal_type: str | None) -> str:
    return SIGNAL_TYPE_TO_DECAY_CATEGORY.get((signal_type or "").strip(), DEFAULT_DECAY_CATEGORY)


def decay_expires_at_for(created_at: datetime | None, decay_category: str) -> datetime:
    base = created_at or datetime.utcnow()
    days = DECAY_HALF_LIFE_DAYS.get(decay_category, DECAY_HALF_LIFE_DAYS[DEFAULT_DECAY_CATEGORY])
    return base + timedelta(days=days)


def is_decayed(decay_expires_at: datetime | None, now: datetime | None = None) -> bool:
    """A signal with no decay_expires_at yet (not stamped) is treated as NOT decayed —
    absence of a stamp should never look like staleness; run the backfill instead."""
    if decay_expires_at is None:
        return False
    return (now or datetime.utcnow()) >= decay_expires_at


# ── Confidence score (P1 v1 — deterministic, inspectable, no model) ────────
# Every signal in P1 is manually entered (no raw_captures/source_registry
# yet), so there's no automated source-reliability input to lean on. Per
# the architecture doc's own OPEN-Q ("start rule-based, only reach for a
# model if the false-negative rate proves too high"), this scores concrete,
# checkable properties of the signal itself rather than guessing at truth:
#   - a URL means the claim is independently checkable by a human later
#   - a specific (non-generic) source is more accountable than "Manual"
#   - populated signal-type-specific structured fields (an RFP's deadline/
#     scope, or a partnership classification actually grounded in a matched
#     vendor name) mean the signal carries real substance, not just a title
#   - a substantive summary beats a bare one-line title
# Capped at 0.95 (never 1.0 — EPIS-RCM-05: the engine never claims full
# certainty) and floored at 0.3 (a bare signal is still worth logging, just
# visibly less certain than one with corroborating detail).
CONFIDENCE_BASE = 0.5
CONFIDENCE_CAP = 0.95
CONFIDENCE_FLOOR = 0.3
_GENERIC_SOURCE_LABELS = {"", "manual", "unknown", "n/a", "na"}


def compute_confidence_score(sig) -> float:
    score = CONFIDENCE_BASE

    if (getattr(sig, "url", None) or "").strip():
        score += 0.15

    if (getattr(sig, "source", None) or "").strip().lower() not in _GENERIC_SOURCE_LABELS:
        score += 0.15

    signal_type = (getattr(sig, "signal_type", None) or "").strip()
    if signal_type == "rfp" and (getattr(sig, "deadline", None) or (getattr(sig, "scope_description", None) or "").strip()):
        score += 0.15
    elif signal_type == "partnership" and getattr(sig, "partner_classification_matched_vendor", None):
        score += 0.15
    elif signal_type not in ("rfp", "partnership") and (getattr(sig, "product_match", None) or "").strip():
        # generic structured-substance proxy for non-tender/non-partnership types
        score += 0.10

    if len((getattr(sig, "summary", None) or "").strip()) > 40:
        score += 0.05

    return round(min(CONFIDENCE_CAP, max(CONFIDENCE_FLOOR, score)), 2)


def stamp_signal_intelligence(sig) -> None:
    """Sets decay_category / decay_expires_at / confidence_score on a Signal
    ORM instance in place. Called on every save (signal_new, signal_edit)
    and by the one-time backfill script for pre-existing rows. Deliberately
    idempotent and side-effect-free beyond these three fields — does not
    touch source_reliability (P2, needs source_registry) or anything
    Filter/Capture-layer related."""
    sig.decay_category = decay_category_for_signal_type(sig.signal_type)
    sig.decay_expires_at = decay_expires_at_for(sig.created_at, sig.decay_category)
    sig.confidence_score = compute_confidence_score(sig)
