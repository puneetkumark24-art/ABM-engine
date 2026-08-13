"""Canonical email event vocabulary and normalization.

Providers use different names for the same lifecycle event.  Everything is
normalized before it reaches analytics, suppression, or campaign health.
"""
from __future__ import annotations

ALIASES = {
    "send": "accepted", "sent": "accepted", "queued": "accepted",
    "accepted": "accepted",
    "delivery": "delivered", "delivered": "delivered",
    "open": "open", "opened": "open",
    "click": "click", "clicked": "click",
    "soft_bounce": "soft_bounce",
    "deferred": "soft_bounce", "deferral": "soft_bounce",
    "hard_bounce": "hard_bounce",
    "bounce": "hard_bounce", "bounced": "hard_bounce",
    "reject": "rejected", "rejected": "rejected",
    "spam": "complaint", "complaint": "complaint",
    "unsub": "unsubscribe", "unsubscribe": "unsubscribe",
    "unsubscribed": "unsubscribe",
    "reply": "reply", "replied": "reply",
    "failed": "failed",
}


UNKNOWN = "unknown"


def normalize(value: str | None) -> str:
    """Map a provider's event name onto the canonical vocabulary.

    A missing or unrecognized type becomes ``unknown``, never ``delivered``.
    Defaulting the absent case to "delivered" quietly inflates the one number
    the whole deliverability picture rests on -- a malformed webhook, a
    provider adding an event we don't know yet, or a truncated payload would
    each have counted as proof the mail arrived.
    """
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not raw:
        return UNKNOWN
    return ALIASES.get(raw, raw)


# The closed set of things we are willing to act on. `unknown` is deliberately
# NOT a member: an event we cannot classify is recorded for audit and drives
# nothing. Webhook ingestion rejects anything outside this set.
CANONICAL = set(ALIASES.values())
BOUNCES = {"soft_bounce", "hard_bounce"}
NEGATIVE = BOUNCES | {"rejected", "failed", "complaint", "unsubscribe"}
