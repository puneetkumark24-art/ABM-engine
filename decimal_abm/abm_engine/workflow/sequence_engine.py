"""
abm_engine/workflow/sequence_engine.py
─────────────────────────────────────────
High-level API the orchestrator calls. Everything DB-shaped lives in
sequence_db.py; this module is the policy layer:

    ensure_default_sequence()   idempotent — recreates today's implicit
                                 cadence (5 touches, EMAIL+LINKEDIN together,
                                 3-day gaps) as an explicit, editable sequence.
    backfill_enrollments()      idempotent — enrolls every active contact that
                                 isn't enrolled yet, at their current progress
                                 (current_touch), so nobody's sequence resets.
    get_contacts_due(limit)     replaces database.db.get_contacts_due_for_outreach:
                                 same compliance gates, but cadence comes from
                                 sequence_steps instead of a hardcoded constant.
    advance(contact_id)         call after a successful send.
    pause(contact_id, reason)   call on reply / unsubscribe / do-not-contact.

Falling back safely: if anything here raises (e.g. tables not migrated on a
machine that hasn't pulled this change yet), the orchestrator catches it and
falls back to the original database.db.get_contacts_due_for_outreach so a
partial deploy never breaks outreach entirely.
"""
from __future__ import annotations

from loguru import logger

from ..database.db import get_conn
from . import sequence_db as sdb

DEFAULT_SEQUENCE_NAME = "Default 5-Touch"


def ensure_default_sequence() -> int:
    """
    Recreates the cadence the engine already used before Phase 1:
    5 steps, EMAIL+LINKEDIN sent together each step (touch_type is decided per
    channel-availability in orchestrator, same as before), 3 days between
    steps, step 5 is final.
    """
    sdb.init_sequence_tables()
    existing = sdb.get_sequence_by_name(DEFAULT_SEQUENCE_NAME)
    seq_id = existing["id"] if existing else sdb.create_sequence(DEFAULT_SEQUENCE_NAME, relationship_type=None)

    for step_number in range(1, 6):
        sdb.add_step(
            sequence_id=seq_id,
            step_number=step_number,
            channel="BOTH",
            wait_days_after_previous=3,
            is_final=(step_number == 5),
        )
    logger.info("Default sequence ready: id={} ('{}', 5 steps / 3-day cadence)", seq_id, DEFAULT_SEQUENCE_NAME)
    return seq_id


def backfill_enrollments() -> dict:
    """
    For every active contact with no enrollment yet, enroll them in the
    sequence matching their relationship_type (or the default), starting at
    their existing current_touch so in-flight contacts don't restart at
    touch 1.
    """
    default_seq = ensure_default_sequence()
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("""
        SELECT c.id, c.relationship_type, c.current_touch
        FROM contacts c
        LEFT JOIN sequence_enrollments e ON e.contact_id = c.id
        WHERE c.is_active = 1 AND e.id IS NULL
    """).fetchall()]

    enrolled = 0
    for row in rows:
        seq = sdb.sequence_for_relationship_type(row["relationship_type"]) or {"id": default_seq}
        sdb.enroll(row["id"], seq["id"], current_step=row.get("current_touch") or 0)
        enrolled += 1

    logger.info("Sequence backfill: {} contact(s) newly enrolled", enrolled)
    return {"enrolled": enrolled, "already_enrolled": len(rows) - enrolled}


def get_contacts_due(limit: int = 20) -> list[dict]:
    """
    Same shape/contract as database.db.get_contacts_due_for_outreach(limit),
    but "due" is computed from each contact's actual sequence step cadence
    instead of a hardcoded "-3 days" / "<5" check. Same compliance gates
    (do_not_contact, consent_status, replied, is_active) still apply.
    """
    backfill_enrollments()  # cheap no-op once steady-state; guarantees no orphan contacts
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.*, e.id AS enrollment_id, e.current_step, e.status AS enrollment_status
        FROM contacts c
        JOIN sequence_enrollments e ON e.contact_id = c.id AND e.status = 'ACTIVE'
        JOIN sequence_steps s ON s.sequence_id = e.sequence_id
                              AND s.step_number = e.current_step + 1
        WHERE c.is_active = 1
          AND c.replied = 0
          AND COALESCE(c.do_not_contact, 0) = 0
          AND COALESCE(c.consent_status, '') != 'denied'
          AND datetime(
                CASE WHEN e.current_step = 0 THEN e.enrolled_at ELSE e.updated_at END,
                '+' || s.wait_days_after_previous || ' days'
              ) <= datetime('now')
        ORDER BY
            CASE c.tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END,
            c.has_warm_relationship DESC,
            c.priority_score DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def advance(contact_id: int) -> None:
    """Call once per contact after a send succeeds (email and/or LinkedIn —
    one call regardless of how many channels fired this step, since BOTH is
    one sequence step)."""
    enrollment = sdb.get_active_enrollment_for_contact(contact_id)
    if not enrollment:
        return  # not enrolled (e.g. backfill hasn't run yet) — orchestrator's
                 # own current_touch increment still covers this contact
    step = sdb.get_step(enrollment["sequence_id"], enrollment["current_step"] + 1)
    is_final = bool(step["is_final"]) if step else True
    sdb.advance_enrollment(enrollment["id"], is_final_step=is_final)


def pause(contact_id: int, reason: str) -> None:
    """Call on reply / unsubscribe / manual do-not-contact. Idempotent."""
    sdb.pause_all_for_contact(contact_id, reason=reason)
    logger.info("Sequence paused for contact {} ({})", contact_id, reason)
