"""The end-to-end orchestrator — one tick runs the whole engine:

  due sequence steps (compliance + KSA-window gated)
    -> AI draft (anonymized, QC'd; c-suite auto-held for human)
    -> Draft record (pending / auto-approvable per QC)
    -> dry-run delivery (idempotent, evented)
    -> sequence advance
    -> attribution touch + analytics event
  then for every touched org:
    -> engagement rollup -> account_scores -> re-tier -> events

This is the 'zero human intervention' loop in embryo, with the three hard
stops intact: c-suite drafts are never auto-approved, nothing sends for real
(dry_run transport only), and every gate lives in the called service, not here.
Run it from a scheduler (cron / engine_scheduler) or POST /engine/tick."""
from __future__ import annotations
from datetime import datetime
import threading
import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session
import models
import models_ext as mx
from sequences import engine as seq_engine
from . import ai_gen, delivery, attribution, analytics, engagement, marketing_ext

_LOCAL_TICK_LOCK = threading.Lock()
_PG_TICK_LOCK_KEY = 742_603_219


def _acquire_tick_lock(db: Session):
    """Serialize whole ticks across processes. Returns a release handle, or None.

    Why the lock is NOT taken on `db`: a PostgreSQL *session* advisory lock
    belongs to the specific backend connection that took it, and a SQLAlchemy
    Session returns its connection to the pool on every commit. This tick
    commits internally several times (`_dispatch_human_approved`, then
    `_run_tick_locked`), and under concurrency the Session demonstrably comes
    back on a DIFFERENT backend afterwards -- at which point
    `pg_advisory_unlock` runs on the wrong connection, returns false, and the
    real lock is never released. Measured directly against a disposable
    PostgreSQL (tests/test_tick_lock.py): taking the lock on the Session
    stranded a lock in 3 of 4 concurrent runs, and the stranded locks
    accumulate on idle pooled connections until every future tick reports
    "another engine tick is already running" and the engine silently stops
    dispatching forever. That failure looks exactly like normal idle output,
    which is what makes it dangerous.

    So the lock is held on a dedicated connection checked out for the tick's
    duration and never returned to the pool mid-tick. It is also self-healing:
    if the process dies, the connection closes and PostgreSQL drops the lock
    automatically -- no manual unjamming, unlike a stranded pooled connection.

    SQLite (dev/tests) has no cross-process story; a process-local lock is the
    honest equivalent rather than a pretence of distributed mutual exclusion.
    """
    if db.get_bind().dialect.name == "postgresql":
        conn = db.get_bind().connect()
        try:
            got = conn.execute(text("SELECT pg_try_advisory_lock(:key)"),
                               {"key": _PG_TICK_LOCK_KEY}).scalar()
        except Exception:
            conn.close()
            raise
        if not got:
            conn.close()
            return None
        return conn
    return _LOCAL_TICK_LOCK if _LOCAL_TICK_LOCK.acquire(blocking=False) else None


def _release_tick_lock(handle) -> None:
    if handle is None:
        return
    if handle is _LOCAL_TICK_LOCK:
        if _LOCAL_TICK_LOCK.locked():
            _LOCAL_TICK_LOCK.release()
        return
    try:
        handle.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _PG_TICK_LOCK_KEY})
    finally:
        handle.close()   # closing alone would release it too — belt and braces


def _dispatch_human_approved(db: Session, now: datetime, limit: int) -> dict:
    """Complete the lifecycle for drafts released by a human reviewer.

    Human-held drafts used to stop forever after the Approve button changed
    `pending` to `approved` -- the Approvals screen had an Approve button with
    nothing downstream that ever acted on it. Resolve the one eligible
    enrollment, re-check compliance (state may have changed since the draft
    was written), simulate delivery idempotently, then advance exactly once.
    Ambiguous or unsafe rows remain approved and are reported, never guessed.
    """
    result = {"dispatched": 0, "advanced": 0, "blocked": [], "org_ids": []}
    q = (db.query(models.Draft)
         .filter(models.Draft.status == "approved")
         .order_by(models.Draft.reviewed_at.asc().nullsfirst(), models.Draft.created_at.asc())
         .limit(limit))
    if db.bind.dialect.name == "postgresql":
        # A cron double-fire or a human clicking "Run engine now" twice while
        # the first click is still in flight would otherwise both select the
        # same approved draft and both send it -- a real duplicate customer
        # email, not just a harmless double-write. FOR UPDATE SKIP LOCKED:
        # each concurrent tick locks only the rows it actually claims: any
        # row a concurrent tick already has locked is silently skipped
        # (never blocked on, never double-processed) rather than the two
        # ticks racing to update the same row. SQLite has no session
        # concurrency to speak of (dev/tests only), so this is Postgres-only.
        q = q.with_for_update(skip_locked=True)
    drafts = q.all()
    for draft in drafts:
        if not draft.person_id:
            result["blocked"].append({"draft_id": draft.id, "reason": "missing person"})
            continue
        # Contactability is re-checked here, before branching on draft kind,
        # because state can have changed since the draft was written: the
        # person may have unsubscribed, bounced, or had consent withdrawn
        # while the draft sat in the review queue.
        person = db.get(models.Person, draft.person_id)
        contactable, reason = seq_engine.is_contactable(person)
        if not contactable or not person.primary_email:
            result["blocked"].append({"draft_id": draft.id,
                                      "reason": reason if not contactable else "missing primary email"})
            continue

        # ── campaign drafts ──────────────────────────────────────────────
        # A c-suite recipient of a marketing campaign gets a real approval
        # draft instead of being counted as sent (marketing.send_campaign).
        # Releasing it has to complete the CAMPAIGN's delivery, not a
        # sequence's -- different message identity, different completion
        # bookkeeping -- so it branches before the sequence path below.
        # Note campaign drafts carry sequence_step=0, which is falsy, so this
        # branch must come before any `if not draft.sequence_step` guard.
        if (draft.source or "").startswith("campaign:"):
            campaign_id = draft.source.split(":", 1)[1]
            # Same deterministic id marketing.send_campaign would have used,
            # so a retry can never produce a second message for this person.
            message_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                        f"drip:campaign:{campaign_id}:{person.id}"))
            msg = db.get(mx.EmailMessage, message_id)
            if msg is None:
                msg = mx.EmailMessage(id=message_id, campaign_id=campaign_id,
                                      person_id=person.id, to_email=person.primary_email,
                                      variant="human-approved")
                db.add(msg); db.flush()
            req = delivery.enqueue(db, message_id=message_id,
                                   to_email=person.primary_email, subject=draft.subject,
                                   body=draft.body, transport="dry_run")
            if req.status != "sent":
                result["blocked"].append({"draft_id": draft.id,
                                          "reason": f"delivery status={req.status}"})
                continue
            msg.status = "sent"; msg.sent_at = now
            draft.status = "sent"; draft.sent_at = now
            attribution.record_touch(db, org_id=draft.org_id, person_id=person.id,
                                     channel="email", campaign_id=campaign_id,
                                     occurred_at=now)
            analytics.ingest(db, "email.campaign.human_approved", subject_type="person",
                             subject_id=person.id, props={"campaign_id": campaign_id})
            # The campaign stays `awaiting_approval` until the last executive
            # draft is resolved, so its status never claims completion while a
            # human decision is still outstanding.
            remaining = db.query(models.Draft).filter(
                models.Draft.source == f"campaign:{campaign_id}",
                models.Draft.id != draft.id,
                models.Draft.status.in_(["pending", "approved"])).count()
            campaign = db.get(mx.EmailCampaign, campaign_id)
            if campaign is not None and remaining == 0:
                campaign.status = "sent"
            result["dispatched"] += 1
            if draft.org_id:
                result["org_ids"].append(draft.org_id)
            continue

        # ── sequence drafts ──────────────────────────────────────────────
        if not draft.sequence_step:
            result["blocked"].append({"draft_id": draft.id, "reason": "missing sequence step"})
            continue
        matches = (db.query(models.SequenceEnrollment)
                   .filter(models.SequenceEnrollment.person_id == draft.person_id,
                           models.SequenceEnrollment.status == "ACTIVE",
                           models.SequenceEnrollment.current_step == int(draft.sequence_step) - 1)
                   .all())
        if len(matches) != 1:
            result["blocked"].append({"draft_id": draft.id,
                                      "reason": f"expected one active enrollment, found {len(matches)}"})
            continue
        enr = matches[0]
        req = delivery.enqueue(db, message_id=f"seq-{enr.id}-{draft.sequence_step}",
                               to_email=person.primary_email, subject=draft.subject,
                               body=draft.body, transport="dry_run")
        if req.status != "sent":
            result["blocked"].append({"draft_id": draft.id, "reason": f"delivery status={req.status}"})
            continue
        draft.status = "sent"
        draft.sent_at = now
        seq_engine.advance(db, enr.id, now=now)
        attribution.record_touch(db, org_id=enr.org_id, person_id=person.id,
                                 channel="email", occurred_at=now)
        analytics.ingest(db, "sequence.step.sent", subject_type="person",
                         subject_id=person.id,
                         props={"step": draft.sequence_step, "human_approved": True})
        result["dispatched"] += 1
        result["advanced"] += 1
        if enr.org_id:
            result["org_ids"].append(enr.org_id)
    db.commit()
    return result


def _run_tick_locked(db: Session, limit: int = 10, respect_send_window: bool = True,
                     now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    report = {"due": 0, "drafted": 0, "held_for_human": 0, "qc_failed": 0,
              "sent_dry_run": 0, "advanced": 0, "approved_dispatched": 0,
              "approved_blocked": [], "existing_drafts_skipped": 0,
              "orgs_rescored": [], "skipped": None}

    approved = _dispatch_human_approved(db, now, limit)
    report["approved_dispatched"] = approved["dispatched"]
    report["approved_blocked"] = approved["blocked"]
    report["sent_dry_run"] += approved["dispatched"]
    report["advanced"] += approved["advanced"]

    due = seq_engine.get_due(db, limit=limit, respect_send_window=respect_send_window, now=now)
    if not due and respect_send_window:
        allowed, reason = __import__("sequences.send_window", fromlist=["is_within_send_window"]).is_within_send_window()
        if not allowed:
            report["skipped"] = f"send window closed: {reason}"
            return report
    report["due"] = len(due)

    touched_orgs: set[str] = set(approved["org_ids"])
    for row in due:
        person, enr, step = row["person"], row["enrollment"], row["next_step"]

        # A c-suite enrollment stays "due" (current_step unchanged) for as
        # long as its draft sits pending human review, since advance() only
        # runs after dispatch. Without this check, every tick regenerated
        # ANOTHER pending draft for the same person+step, flooding the
        # Approvals queue with duplicates of the same still-unreviewed
        # decision. One actionable draft per person/step; the reviewer
        # resolves that row before any further draft is generated for it.
        existing = (db.query(models.Draft.id)
                    .filter(models.Draft.person_id == person.id,
                            models.Draft.sequence_step == step.step_number,
                            models.Draft.status.in_(["pending", "approved"]))
                    .first())
        if existing:
            report["existing_drafts_skipped"] += 1
            continue

        # 1) AI draft (anonymized + QC). c-suite => held for human, not sent.
        gen = ai_gen.generate(db, "email", person_id=person.id, org_id=enr.org_id,
                              context={"sequence_step": step.step_number,
                                       "channel": step.channel})
        if gen.status != "qc_passed":
            report["qc_failed"] += 1
            continue
        held = any("human approval" in i for i in (gen.qc or {}).get("issues", []))
        # QC (above) deliberately runs on the pre-merge text -- it checks for
        # placeholders OTHER than the allowed {name}/{sender}/{institution}/
        # {role} merge tags. Those allowed tags must still be resolved before
        # this draft is stored/delivered, or a real recipient would see the
        # literal "{name}" text. render_merge() already exists and is tested
        # (used by the marketing-campaign send path) but was never wired into
        # this per-sequence-step draft path -- wiring it in now.
        body = marketing_ext.render_merge(db, gen.output, person)
        subject = marketing_ext.render_merge(db, f"Step {step.step_number}", person)
        draft = models.Draft(org_id=enr.org_id, person_id=person.id,
                             channel="email", subject=subject,
                             body=body,
                             status="pending" if held else "approved",
                             source="ai", sequence_step=step.step_number)
        db.add(draft); db.flush()
        report["drafted"] += 1
        if held:
            report["held_for_human"] += 1
            continue                       # c-suite: stops here until a human approves

        # 2) dry-run delivery (idempotent per enrollment+step)
        req = delivery.enqueue(db, message_id=f"seq-{enr.id}-{step.step_number}",
                               to_email=person.primary_email or "missing@example.invalid",
                               subject=draft.subject, body=draft.body,
                               transport="dry_run")
        if req.status == "sent":
            report["sent_dry_run"] += 1
            draft.status = "sent"; draft.sent_at = now

        # 3) advance the sequence + record the touch
        seq_engine.advance(db, enr.id, now=now)
        report["advanced"] += 1
        attribution.record_touch(db, org_id=enr.org_id, person_id=person.id,
                                 channel="email", occurred_at=now)
        analytics.ingest(db, "sequence.step.sent", subject_type="person",
                         subject_id=person.id, props={"step": step.step_number})
        if enr.org_id:
            touched_orgs.add(enr.org_id)

    # 4) close the loop: engagement rollup + rescore + re-tier per touched org
    for org_id in touched_orgs:
        result = engagement.rollup_org(db, org_id)
        report["orgs_rescored"].append({"org_id": org_id, **result})

    db.commit()
    return report


def run_tick(db: Session, limit: int = 10, respect_send_window: bool = True,
             now: datetime | None = None) -> dict:
    """Run exactly one engine cycle, and only one at a time.

    A cron double-fire, a scheduler restart overlapping the previous run, or a
    human clicking "Run engine now" twice would otherwise interleave two ticks.
    The row-level `FOR UPDATE SKIP LOCKED` inside `_dispatch_human_approved`
    already prevents the worst outcome (the same approved draft being
    dispatched twice), and stays in place; this outer lock additionally stops
    two ticks doing overlapping work at all, which keeps tick reports
    meaningful and avoids redundant AI generation. Losing ticks exit
    immediately with a reason rather than blocking.
    """
    handle = _acquire_tick_lock(db)
    if handle is None:
        return {"due": 0, "drafted": 0, "held_for_human": 0, "qc_failed": 0,
                "sent_dry_run": 0, "advanced": 0, "approved_dispatched": 0,
                "approved_blocked": [], "existing_drafts_skipped": 0,
                "orgs_rescored": [],
                "skipped": "another engine tick is already running"}
    try:
        return _run_tick_locked(db, limit=limit,
                                respect_send_window=respect_send_window, now=now)
    finally:
        _release_tick_lock(handle)
