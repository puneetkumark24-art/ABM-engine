"""
meetings.py — Final wave: the meetings module (HubSpot-gap closure, engine
level). Schedule / complete / cancel / no-show, conflict detection per owner,
upcoming agenda, and RFC-5545 ICS export (stdlib only) so any calendar app can
import a DRIP meeting. External calendar sync (Google/Outlook) stays
credential-gated behind this same service.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_final as mf

_STATUSES = {"scheduled", "completed", "cancelled", "no_show"}


def schedule(db: Session, title: str, starts_at: datetime,
             duration_minutes: int = 30, org_id: str | None = None,
             person_id: str | None = None, owner: str = "unassigned",
             location: str = "", agenda: str = "") -> mf.Meeting:
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    # conflict detection: same owner, overlapping window, still scheduled
    clash = (db.query(mf.Meeting)
             .filter(mf.Meeting.owner == owner, mf.Meeting.status == "scheduled",
                     mf.Meeting.starts_at < ends_at, mf.Meeting.ends_at > starts_at)
             .first())
    if clash is not None:
        raise ValueError(f"conflict: owner already has '{clash.title}' at that time")
    m = mf.Meeting(title=title, starts_at=starts_at, ends_at=ends_at, org_id=org_id,
                   person_id=person_id, owner=owner, location=location, agenda=agenda)
    db.add(m); db.commit()
    return m


def set_status(db: Session, meeting_id: str, status: str,
               outcome_notes: str = "") -> mf.Meeting:
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {sorted(_STATUSES)}")
    m = db.get(mf.Meeting, meeting_id)
    if m is None:
        raise ValueError("meeting not found")
    m.status = status
    if outcome_notes:
        m.outcome_notes = outcome_notes
    db.commit()
    return m


def upcoming(db: Session, owner: str | None = None, days: int = 14,
             now: datetime | None = None) -> list[mf.Meeting]:
    now = now or datetime.utcnow()
    q = (db.query(mf.Meeting)
         .filter(mf.Meeting.status == "scheduled",
                 mf.Meeting.starts_at >= now,
                 mf.Meeting.starts_at <= now + timedelta(days=days)))
    if owner:
        q = q.filter(mf.Meeting.owner == owner)
    return q.order_by(mf.Meeting.starts_at).all()


def to_ics(m: mf.Meeting) -> str:
    """RFC-5545 calendar entry — importable by Outlook/Google/Apple."""
    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")
    desc = (m.agenda or "").replace("\n", "\\n")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DRIP//Meetings//EN",
        "BEGIN:VEVENT",
        f"UID:{m.id}@drip",
        f"DTSTAMP:{fmt(m.created_at or datetime.utcnow())}",
        f"DTSTART:{fmt(m.starts_at)}",
        f"DTEND:{fmt(m.ends_at or m.starts_at)}",
        f"SUMMARY:{m.title}",
        f"LOCATION:{m.location or ''}",
        f"DESCRIPTION:{desc}",
        "END:VEVENT", "END:VCALENDAR", ""])
