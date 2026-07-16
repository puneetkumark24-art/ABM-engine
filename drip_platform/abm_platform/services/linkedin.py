"""Module 12 — LinkedIn Automation Engine (safety-first).
LI-001: NO action executes unless the 'linkedin' circuit breaker is healthy.
LI-002: per-seat daily caps enforced. LI-003: reply => account-centric pause
via the sequence engine. The executor is a stub that records actions — there
is no real LinkedIn client here by design; it gets added last per the roadmap,
behind this same gate."""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_ext as mx
from sequences import engine as seq_engine
from abm_platform.events import Event, publish

BREAKER = "linkedin"


def get_breaker(db: Session) -> mx.CircuitBreaker:
    b = db.query(mx.CircuitBreaker).filter_by(name=BREAKER).first()
    if b is None:
        b = mx.CircuitBreaker(name=BREAKER, healthy=True)
        db.add(b); db.commit()
    return b


def trip_breaker(db: Session, reason: str) -> mx.CircuitBreaker:
    b = get_breaker(db)
    b.healthy = False; b.reason = reason; b.tripped_at = datetime.utcnow()
    db.commit()
    publish(Event("linkedin.circuit_breaker.tripped", payload={"reason": reason}))
    return b


def reset_breaker(db: Session) -> mx.CircuitBreaker:
    b = get_breaker(db)
    b.healthy = True; b.reason = None; b.tripped_at = None
    db.commit()
    return b


def create_seat(db: Session, owner: str, daily_limit: int = 20) -> mx.LiSeat:
    s = mx.LiSeat(owner=owner, daily_limit=daily_limit)
    db.add(s); db.commit()
    return s


def _reset_if_new_day(db: Session, seat: mx.LiSeat) -> None:
    if seat.last_reset and datetime.utcnow() - seat.last_reset > timedelta(days=1):
        seat.actions_today = 0
        seat.last_reset = datetime.utcnow()


def queue_action(db: Session, seat_id: str, person_id: str,
                 action_type: str = "connect") -> tuple[mx.LiAction | None, str]:
    """Gate order: breaker -> seat state -> daily cap. Blocked actions are
    recorded (status=blocked) so nothing silently disappears."""
    b = get_breaker(db)
    seat = db.get(mx.LiSeat, seat_id)
    if seat is None:
        return None, "seat_not_found"
    _reset_if_new_day(db, seat)

    if not b.healthy:                                     # LI-001 hard gate
        a = mx.LiAction(seat_id=seat_id, person_id=person_id, action_type=action_type,
                        status="blocked", detail=f"circuit breaker: {b.reason}")
        db.add(a); db.commit()
        return a, "breaker_tripped"
    if seat.status != "active":
        return None, f"seat_{seat.status}"
    if seat.actions_today >= seat.daily_limit:            # LI-002
        a = mx.LiAction(seat_id=seat_id, person_id=person_id, action_type=action_type,
                        status="blocked", detail="daily cap reached")
        db.add(a); db.commit()
        return a, "daily_cap"

    a = mx.LiAction(seat_id=seat_id, person_id=person_id, action_type=action_type, status="queued")
    db.add(a); db.commit()
    return a, "queued"


def execute_pending(db: Session, seat_id: str, limit: int = 10) -> dict:
    """Stub executor: marks queued actions as sent and counts them against the
    seat's cap. A real client would replace ONLY the marked line."""
    b = get_breaker(db)
    if not b.healthy:
        return {"executed": 0, "reason": "breaker_tripped"}
    seat = db.get(mx.LiSeat, seat_id)
    _reset_if_new_day(db, seat)
    pending = (db.query(mx.LiAction)
               .filter_by(seat_id=seat_id, status="queued")
               .order_by(mx.LiAction.scheduled_at).limit(limit).all())
    executed = 0
    for a in pending:
        if seat.actions_today >= seat.daily_limit:
            break
        a.status = "sent"                                  # ← stub: no real call
        a.executed_at = datetime.utcnow()
        seat.actions_today += 1
        executed += 1
        publish(Event("linkedin.action.sent", key=a.person_id,
                      payload={"type": a.action_type}))
    db.commit()
    return {"executed": executed, "remaining_quota": seat.daily_limit - seat.actions_today}


def register_reply(db: Session, action_id: str) -> dict:
    """LI-003: a reply pauses the person AND their whole account (ACC-001)."""
    a = db.get(mx.LiAction, action_id)
    if a is None:
        return {"error": "action not found"}
    a.status = "replied"
    db.commit()
    result = seq_engine.pause_on_reply(db, a.person_id, reason="linkedin_reply")
    publish(Event("linkedin.reply.received", key=a.person_id, payload=result))
    return result
