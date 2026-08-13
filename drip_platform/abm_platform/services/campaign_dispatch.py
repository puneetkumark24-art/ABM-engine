"""Restart-safe, observable campaign execution on top of the durable job queue."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models_ext as mx
from . import jobs, marketing

ACTIVE = {"queued", "running", "cancelling"}


def _view(run: mx.CampaignDispatchRun) -> dict:
    out = {k: getattr(run, k) for k in (
        "id", "campaign_id", "status", "transport", "batch_size", "total",
        "processed", "sent", "blocked", "held_for_human", "existing_skipped",
        "cancel_requested", "last_error", "created_at", "started_at", "finished_at")}
    # Job.result is JSON. Returning raw datetimes makes a successful batch fail
    # during job completion and retry after its delivery transaction committed.
    for key in ("created_at", "started_at", "finished_at"):
        if out[key] is not None:
            out[key] = out[key].isoformat()
    out["failed"] = max(0, out["processed"] - out["sent"] - out["blocked"]
                        - out["held_for_human"] - out["existing_skipped"])
    return out


def start(db: Session, campaign_id: str, batch_size: int = 100,
          requested_transport: str = "dry_run") -> dict:
    camp = db.get(mx.EmailCampaign, campaign_id)
    if camp is None:
        raise ValueError("campaign not found")
    if camp.approval_status != "approved":
        raise ValueError("campaign must be approved before dispatch")
    # Validate the requested transport BEFORE the existing-run early return.
    # Otherwise an unrecognised value -- "sendgrid", a typo, anything -- is
    # silently ignored whenever a run is already active, and the caller gets
    # back a dry_run run with a 200. Nothing unsafe is sent either way, but the
    # operator would be told "dispatch started" for a transport the system
    # never accepted. An invalid argument should be an error regardless of what
    # else happens to be running.
    if requested_transport not in {"dry_run", "configured"}:
        raise ValueError("requested_transport must be dry_run or configured")
    current = (db.query(mx.CampaignDispatchRun)
               .filter(mx.CampaignDispatchRun.campaign_id == campaign_id,
                       mx.CampaignDispatchRun.status.in_(ACTIVE)).first())
    if current:
        return _view(current)
    if requested_transport == "dry_run":
        transport = "dry_run"
    elif requested_transport == "configured":
        from . import send_activation
        transport, reason = send_activation.guard_real_send(db)
        if transport == "dry_run":
            raise ValueError("live dispatch blocked: " + reason)
    else:
        raise ValueError("requested_transport must be dry_run or configured")
    size = max(1, min(int(batch_size), 1000))
    members = marketing.resolve_members(db, camp.audience_id)
    run = mx.CampaignDispatchRun(campaign_id=campaign_id, batch_size=size,
                                 total=len(members), transport=transport)
    db.add(run); db.flush()
    for position, person in enumerate(members):
        db.add(mx.CampaignDispatchRecipient(run_id=run.id, person_id=person.id,
                                            position=position))
    if not members:
        run.status = "completed"; run.finished_at = datetime.utcnow()
    else:
        jobs.enqueue(db, "campaign_dispatch_batch", {"run_id": run.id},
                     idempotency_key=f"{run.id}:0", priority=80)
    db.commit()
    return _view(run)


def process_batch(db: Session, run_id: str) -> dict:
    run = db.get(mx.CampaignDispatchRun, run_id)
    if run is None:
        raise ValueError("dispatch run not found")
    if run.status not in ACTIVE:
        return _view(run)
    if run.cancel_requested:
        run.status = "cancelled"; run.finished_at = datetime.utcnow()
        return _view(run)
    run.status = "running"
    run.started_at = run.started_at or datetime.utcnow()
    rows = (db.query(mx.CampaignDispatchRecipient)
            .filter_by(run_id=run.id, status="pending")
            .order_by(mx.CampaignDispatchRecipient.position)
            .with_for_update(skip_locked=True).limit(run.batch_size).all())
    if not rows:
        run.status = "completed"; run.finished_at = datetime.utcnow()
        camp = db.get(mx.EmailCampaign, run.campaign_id)
        camp.status = ("attention_required" if _view(run)["failed"] else
                       ("awaiting_approval" if run.held_for_human else "sent"))
        return _view(run)
    people = {p.id: p for p in marketing.resolve_members(
        db, db.get(mx.EmailCampaign, run.campaign_id).audience_id)}
    ids = [r.person_id for r in rows]
    before = {person_id for (person_id,) in db.query(mx.EmailMessage.person_id).filter(
        mx.EmailMessage.campaign_id == run.campaign_id,
        mx.EmailMessage.person_id.in_(ids)).all()}
    marketing.send_campaign(db, run.campaign_id, transport=run.transport,
                            person_ids=ids, finalize=False, commit=False)
    emitted = {m.person_id: m for m in db.query(mx.EmailMessage).filter(
        mx.EmailMessage.campaign_id == run.campaign_id,
        mx.EmailMessage.person_id.in_(ids)).all()}
    now = datetime.utcnow()
    for row in rows:
        person = people.get(row.person_id)
        if person is None:
            row.status, row.reason = "blocked", "no_longer_in_audience"
        else:
            allowed, reason = marketing.is_sendable(db, person)
            if not allowed:
                row.status, row.reason = "blocked", reason
            elif person.seniority_level == "c_suite":
                row.status, row.reason = "held", "human_approval"
            elif emitted.get(person.id) and emitted[person.id].status != "sent":
                row.status, row.reason = "failed", f"delivery_{emitted[person.id].status}"
            elif person.id in before:
                row.status, row.reason = "existing", "idempotent_replay"
            else:
                row.status = "sent"
        row.processed_at = now
    run.processed += len(rows)
    run.sent += sum(r.status == "sent" for r in rows)
    run.blocked += sum(r.status == "blocked" for r in rows)
    run.held_for_human += sum(r.status == "held" for r in rows)
    run.existing_skipped += sum(r.status == "existing" for r in rows)
    # SessionLocal has autoflush disabled. Persist claimed recipient outcomes
    # before counting pending rows or this batch is selected again forever.
    db.flush()
    remaining = db.query(mx.CampaignDispatchRecipient).filter_by(
        run_id=run.id, status="pending").count()
    if run.cancel_requested:
        run.status = "cancelled"; run.finished_at = now
    elif remaining:
        jobs.enqueue(db, "campaign_dispatch_batch", {"run_id": run.id},
                     idempotency_key=f"{run.id}:{run.processed}", priority=80)
    else:
        run.status = "completed"; run.finished_at = now
        camp = db.get(mx.EmailCampaign, run.campaign_id)
        camp.status = ("attention_required" if _view(run)["failed"] else
                       ("awaiting_approval" if run.held_for_human else "sent"))
    return _view(run)


def cancel(db: Session, run_id: str) -> dict:
    run = db.get(mx.CampaignDispatchRun, run_id)
    if run is None:
        raise ValueError("dispatch run not found")
    if run.status in ACTIVE:
        run.cancel_requested = True
        run.status = "cancelling"
        db.commit()
    return _view(run)


def get(db: Session, run_id: str) -> dict:
    run = db.get(mx.CampaignDispatchRun, run_id)
    if run is None:
        raise ValueError("dispatch run not found")
    view = _view(run)
    view["percent"] = round(100 * run.processed / run.total, 1) if run.total else 100.0
    return view
