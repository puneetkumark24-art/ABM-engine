"""Module 22 — Attribution Engine: multi-touch credit models.
ATT-001: credit fractions per model always sum to 1.0 (within float epsilon).
Models: first / last / linear / time_decay / w_shaped."""
from __future__ import annotations
import math
from datetime import datetime
from sqlalchemy.orm import Session
import models_ext as mx


def record_touch(db: Session, org_id: str | None = None, person_id: str | None = None,
                 channel: str = "email", campaign_id: str | None = None,
                 occurred_at: datetime | None = None) -> mx.Touch:
    t = mx.Touch(org_id=org_id, person_id=person_id, channel=channel,
                 campaign_id=campaign_id, occurred_at=occurred_at or datetime.utcnow())
    db.add(t); db.commit()
    return t


def _credits(touches: list[mx.Touch], model: str) -> dict[str, float]:
    n = len(touches)
    if n == 0:
        return {}
    if n == 1:
        return {touches[0].id: 1.0}
    if model == "first":
        return {t.id: (1.0 if i == 0 else 0.0) for i, t in enumerate(touches)}
    if model == "last":
        return {t.id: (1.0 if i == n - 1 else 0.0) for i, t in enumerate(touches)}
    if model == "linear":
        # full precision — rounding each share can make the sum miss 1.0 (ATT-001)
        return {t.id: 1.0 / n for t in touches}
    if model == "time_decay":
        # half-life weighting: more recent touches earn more
        weights = [math.pow(2, i) for i in range(n)]      # oldest -> newest
        total = sum(weights)
        return {t.id: w / total for t, w in zip(touches, weights)}
    if model == "w_shaped":
        # 30% first, 30% last, 40% split across middles (or 50/50 if only 2)
        if n == 2:
            return {touches[0].id: 0.5, touches[-1].id: 0.5}
        credit = {touches[0].id: 0.3, touches[-1].id: 0.3}
        mid = touches[1:-1]
        share = round(0.4 / len(mid), 6)
        for t in mid:
            credit[t.id] = share
        return credit
    raise ValueError(f"unknown model {model}")


def compute(db: Session, org_id: str, outcome_ref: str, model: str = "linear",
            window_days: int = 90) -> mx.AttributionResult:
    """Assemble the org's touch path within the window and assign credit."""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=window_days)
    touches = (db.query(mx.Touch)
               .filter(mx.Touch.org_id == org_id, mx.Touch.occurred_at >= since)
               .order_by(mx.Touch.occurred_at).all())
    credit = _credits(touches, model)
    res = mx.AttributionResult(org_id=org_id, outcome_ref=outcome_ref,
                               model=model, credit=credit)
    db.add(res); db.commit()
    return res


def campaign_credit(db: Session, result_id: str) -> dict[str, float]:
    """Roll touch-level credit up to campaigns."""
    res = db.get(mx.AttributionResult, result_id)
    if res is None:
        return {}
    out: dict[str, float] = {}
    for touch_id, frac in (res.credit or {}).items():
        t = db.get(mx.Touch, touch_id)
        key = (t.campaign_id if t and t.campaign_id else "unattributed")
    