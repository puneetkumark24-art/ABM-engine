"""
drip_platform/sequences/engine.py
───────────────────────────────────
Sequence / Journey Engine — ORM policy layer (Enterprise Blueprint Module 08).

The DB-shaped tables live in models.py (SequenceDefinition/Step/Enrollment/
EnrollmentEvent). This module is the policy layer the API and scheduler call:

    ensure_default_sequence(db)          idempotent — the proven 5-touch /
                                          3-day cadence as explicit, editable data.
    enroll_person(db, person_id, ...)    enroll one person (compliance-gated).
    backfill_enrollments(db)             enroll every eligible active person once.
    get_due(db, limit, now, ...)         persons whose next step is due now,
                                          compliance-gated + send-window-gated.
    advance(db, enrollment_id, now)      call after a successful send of the next step.
    pause(db, enrollment_id, reason)     pause one enrollment.
    resume(db, enrollment_id)            resume a paused enrollment.
    pause_on_reply(db, person_id, ...)   ACC-001: reply pauses the person AND
                                          every enrollment at their organization.

Design notes vs. the decimal_abm original this ports:
  * "Due" is computed in Python (load ACTIVE enrollments, compare next_run_at)
    rather than in dialect-specific SQL datetime() — this is deliberately
    portable across SQLite and Postgres and fixes the one place the raw-SQL
    original was dialect-locked.
  * Compliance gates are identical in spirit (do_not_contact / consent_status
    != 'denied' / replied / is_active) but read DRIP's Person columns.
  * next_run_at is materialized on the enrollment so the scheduler can index a
    cheap "due now" query in production instead of recomputing per row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

import models
from .send_window import is_within_send_window

logger = logging.getLogger("drip.sequences.engine")

DEFAULT_SEQUENCE_NAME = "Default 5-Touch"
DEFAULT_STEPS = 5
DEFAULT_WAIT_DAYS = 3
DEFAULT_CHANNEL = "both"

# Tier ordering for prioritisation (HOT first). Mirrors decimal_abm's ORDER BY.
_TIER_RANK = {"HOT": 1, "WARM": 2, "COLD": 3}


# ─────────────────────────────────────────────────────────────
#  Compliance gate (Bible + decimal_abm parity)
# ─────────────────────────────────────────────────────────────
def is_contactable(person: "models.Person") -> tuple[bool, str]:
    """The single source of truth for 'may we enrol / touch this person'.
    Same gates the decimal_abm engine enforced, on DRIP's Person columns."""
    if person is None:
        return False, "person not found"
    if not person.is_active:
        return False, "inactive"
    if person.do_not_contact:
        return False, "do_not_contact"
    if (person.consent_status or "none") == "denied":
        return False, "consent_denied"
    if person.replied:
        return False, "already_replied"
    return True, "ok"


# ─────────────────────────────────────────────────────────────
#  Sequence definitions
# ─────────────────────────────────────────────────────────────
def ensure_default_sequence(db: Session) -> "models.SequenceDefinition":
    """Recreate the cadence the engine already used (5 steps, both channels,
    3-day gaps, step 5 final) as an explicit editable sequence. Idempotent."""
    seq = (
        db.query(models.SequenceDefinition)
        .filter(models.SequenceDefinition.name == DEFAULT_SEQUENCE_NAME)
        .first()
    )
    if seq is None:
        seq = models.SequenceDefinition(
            name=DEFAULT_SEQUENCE_NAME,
            relationship_type=None,
            description="Default cadence ported from decimal_abm Phase 1: "
                        "5 touches, email+linkedin together, 3-day gaps.",
        )
        db.add(seq)
        db.flush()  # get seq.id

    existing_steps = {s.step_number for s in seq.steps}
    for n in range(1, DEFAULT_STEPS + 1):
        if n in existing_steps:
            continue
        db.add(models.SequenceStep(
            sequence_id=seq.id,
            step_number=n,
            channel=DEFAULT_CHANNEL,
            wait_days_after_previous=DEFAULT_WAIT_DAYS,
            is_final=(n == DEFAULT_STEPS),
        ))
    db.commit()
    logger.info("Default sequence ready: id=%s (%s, %d steps / %d-day cadence)",
                seq.id, DEFAULT_SEQUENCE_NAME, DEFAULT_STEPS, DEFAULT_WAIT_DAYS)
    return seq


def sequence_for_relationship_type(db: Session, rel_type: Optional[str]) -> "models.SequenceDefinition":
    """Best-match: a sequence whose relationship_type matches, else the default.
    Mirrors decimal_abm.sequence_for_relationship_type()."""
    if rel_type:
        match = (
            db.query(models.SequenceDefinition)
            .filter(models.SequenceDefinition.relationship_type == rel_type,
                    models.SequenceDefinition.is_active == True)  # noqa: E712
            .first()
        )
        if match:
            return match
    return ensure_default_sequence(db)


def _steps_by_number(db: Session, sequence_id: str) -> dict[int, "models.SequenceStep"]:
    steps = (
        db.query(models.SequenceStep)
        .filter(models.SequenceStep.sequence_id == sequence_id)
        .all()
    )
    return {s.step_number: s for s in steps}


def _next_step(db: Session, sequence_id: str, current_step: int) -> Optional["models.SequenceStep"]:
    return (
        db.query(models.SequenceStep)
        .filter(models.SequenceStep.sequence_id == sequence_id,
                models.SequenceStep.step_number == current_step + 1)
        .first()
    )


def _log(db: Session, enrollment_id: str, event_type: str, step_number: Optional[int] = None,
         detail: Optional[str] = None) -> None:
    db.add(models.SequenceEnrollmentEvent(
        enrollment_id=enrollment_id, event_type=event_type,
        step_number=step_number, detail=detail,
    ))


def _recompute_next_run(db: Session, enrollment: "models.SequenceEnrollment") -> None:
    """Set next_run_at for the step after current_step. Base time is when the
    current step executed (last_step_at) or, before any step, enrolled_at."""
    nxt = _next_step(db, enrollment.sequence_id, enrollment.current_step)
    if nxt is None:
        enrollment.next_run_at = None
        return
    base = enrollment.last_step_at or enrollment.enrolled_at or datetime.utcnow()
    enrollment.next_run_at = base + timedelta(days=int(nxt.wait_days_after_previous or 0))


# ─────────────────────────────────────────────────────────────
#  Enrollment
# ─────────────────────────────────────────────────────────────
def enroll_person(db: Session, person_id: str, sequence_id: Optional[str] = None,
                  current_step: int = 0) -> tuple[Optional["models.SequenceEnrollment"], str]:
    """Enrol a person into a sequence (default if none given). Compliance-gated
    (JRN-001): a person who is inactive / do_not_contact / consent_denied /
    already_replied is NOT enrolled. Idempotent per (person, sequence)."""
    person = db.get(models.Person, person_id)
    ok, reason = is_contactable(person)
    if not ok:
        logger.info("enroll blocked person=%s reason=%s", person_id, reason)
        return None, reason

    # JRN-001 (Phase 9): a globally-suppressed email also blocks enrollment.
    # Local import — models_ext is the Phase-9 extension layer.
    try:
        from models_ext import Suppression
        if person.primary_email and db.query(Suppression).filter_by(
                email=person.primary_email.lower()).first():
            logger.info("enroll blocked person=%s reason=suppressed", person_id)
            return None, "suppressed"
    except ImportError:
        pass  # extension layer not deployed — original gates still apply

    seq = (db.get(models.SequenceDefinition, sequence_id) if sequence_id
           else ensure_default_sequence(db))
    if seq is None:
        return None, "sequence_not_found"

    existing = (
        db.query(models.SequenceEnrollment)
        .filter(models.SequenceEnrollment.person_id == person_id,
                models.SequenceEnrollment.sequence_id == seq.id)
        .first()
    )
    if existing:
        return existing, "already_enrolled"

    enr = models.SequenceEnrollment(
        sequence_id=seq.id,
        person_id=person_id,
        org_id=person.current_org_id,
        current_step=current_step,
        status="ACTIVE",
        enrolled_at=datetime.utcnow(),
    )
    db.add(enr)
    db.flush()
    _recompute_next_run(db, enr)
    _log(db, enr.id, "enrolled", step_number=current_step,
         detail=f"sequence={seq.name}")
    db.commit()
    return enr, "enrolled"


def backfill_enrollments(db: Session) -> dict:
    """Enrol every active, contactable person not yet in the default sequence,
    at their current progress. Idempotent — a no-op once steady-state."""
    seq = ensure_default_sequence(db)
    enrolled_ids = {
        row[0] for row in db.query(models.SequenceEnrollment.person_id)
        .filter(models.SequenceEnrollment.sequence_id == seq.id).all()
    }
    persons = db.query(models.Person).filter(models.Person.is_active == True).all()  # noqa: E712
    enrolled = skipped = 0
    for p in persons:
        if p.id in enrolled_ids:
            continue
        ok, _ = is_contactable(p)
        if not ok:
            skipped += 1
            continue
        enr, _ = enroll_person(db, p.id, sequence_id=seq.id, current_step=0)
        if enr:
            enrolled += 1
    logger.info("Sequence backfill: %d newly enrolled, %d skipped (uncontactable)", enrolled, skipped)
    return {"enrolled": enrolled, "skipped_uncontactable": skipped}


# ─────────────────────────────────────────────────────────────
#  Due / advance / pause
# ─────────────────────────────────────────────────────────────
def get_due(db: Session, limit: int = 20, now: Optional[datetime] = None,
            respect_send_window: bool = True) -> list[dict]:
    """Return enrollments whose next step is due now, gated by compliance AND
    (optionally) the KSA send window. If the send window is closed, returns []
    — a SKIP, not an error, exactly like the decimal_abm behaviour. Sorted
    HOT>WARM>COLD then priority_score desc."""
    now = now or datetime.utcnow()

    if respect_send_window:
        allowed, reason = is_within_send_window()
        if not allowed:
            logger.info("get_due: send window closed (%s) — skipping", reason)
            return []

    active = (
        db.query(models.SequenceEnrollment)
        .filter(models.SequenceEnrollment.status == "ACTIVE")
        .all()
    )
    rows: list[dict] = []
    for enr in active:
        if enr.next_run_at is None or enr.next_run_at > now:
            continue
        nxt = _next_step(db, enr.sequence_id, enr.current_step)
        if nxt is None:
            continue  # nothing left to send; advance() will have completed it
        person = db.get(models.Person, enr.person_id)
        ok, _ = is_contactable(person)
        if not ok:
            continue
        rows.append({
            "enrollment": enr,
            "person": person,
            "next_step": nxt,
            "tier_rank": _TIER_RANK.get((person.tier or "COLD").upper(), 3),
            "priority_score": person.priority_score or 0,
        })

    rows.sort(key=lambda r: (r["tier_rank"], -r["priority_score"]))
    return rows[:limit]


def advance(db: Session, enrollment_id: str, now: Optional[datetime] = None) -> Optional["models.SequenceEnrollment"]:
    """Call once after the next step is successfully sent. Increments
    current_step, records the execution, completes the enrollment if that step
    was final, and recomputes next_run_at otherwise."""
    now = now or datetime.utcnow()
    enr = db.get(models.SequenceEnrollment, enrollment_id)
    if not enr or enr.status != "ACTIVE":
        return enr
    step = _next_step(db, enr.sequence_id, enr.current_step)
    if step is None:
        enr.status = "COMPLETED"
        _log(db, enr.id, "completed", detail="no further steps")
        db.commit()
        return enr

    enr.current_step = step.step_number
    enr.last_step_at = now
    _log(db, enr.id, "step_executed", step_number=step.step_number,
         detail=f"channel={step.channel}")

    if step.is_final:
        enr.status = "COMPLETED"
        enr.next_run_at = None
        _log(db, enr.id, "completed", step_number=step.step_number)
    else:
        _recompute_next_run(db, enr)
        _log(db, enr.id, "advanced", step_number=step.step_number,
             detail=f"next_run_at={enr.next_run_at}")
    db.commit()
    return enr


def pause(db: Session, enrollment_id: str, reason: str) -> Optional["models.SequenceEnrollment"]:
    enr = db.get(models.SequenceEnrollment, enrollment_id)
    if not enr or enr.status not in ("ACTIVE",):
        return enr
    enr.status = "PAUSED"
    enr.pause_reason = reason
    _log(db, enr.id, "paused", step_number=enr.current_step, detail=reason)
    db.commit()
    return enr


def resume(db: Session, enrollment_id: str) -> Optional["models.SequenceEnrollment"]:
    enr = db.get(models.SequenceEnrollment, enrollment_id)
    if not enr or enr.status != "PAUSED":
        return enr
    enr.status = "ACTIVE"
    enr.pause_reason = None
    _recompute_next_run(db, enr)
    _log(db, enr.id, "resumed", step_number=enr.current_step)
    db.commit()
    return enr


def pause_on_reply(db: Session, person_id: str, reason: str = "reply") -> dict:
    """ACC-001 — the account-centric pause. A positive reply pauses the
    replying person's enrollments AND every ACTIVE enrollment at the same
    organization (you never keep auto-touching a bank once anyone there has
    engaged). Also flips person.replied so the compliance gate keeps them out
    going forward. Returns counts."""
    person = db.get(models.Person, person_id)
    if person is None:
        return {"paused_person": 0, "paused_account": 0}

    person.replied = True
    org_id = person.current_org_id

    # 1) the replying person
    person_enrolls = (
        db.query(models.SequenceEnrollment)
        .filter(models.SequenceEnrollment.person_id == person_id,
                models.SequenceEnrollment.status == "ACTIVE")
        .all()
    )
    for enr in person_enrolls:
        enr.status = "PAUSED"
        enr.pause_reason = reason
        _log(db, enr.id, "paused", step_number=enr.current_step, detail=f"{reason} (person)")

    # 2) account-centric cascade — everyone else at the same org
    account_paused = 0
    if org_id:
        others = (
            db.query(models.SequenceEnrollment)
            .filter(models.SequenceEnrollment.org_id == org_id,
                    models.SequenceEnrollment.status == "ACTIVE",
                    models.SequenceEnrollment.person_id != person_id)
            .all()
        )
  