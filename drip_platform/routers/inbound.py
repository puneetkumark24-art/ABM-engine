"""routers/inbound.py — inbound mail polling and transport registration.

Endpoints:
  POST /inbound/poll        run one polling pass (bounces + replies)
  POST /inbound/simulate    feed raw RFC-822 fixtures without a mailbox
  GET  /inbound/transports  which real transports are registered, and why not

The poll endpoint is deliberately a POST you drive from the scheduler (or by
hand) rather than a background thread: polling is cheap, and an explicit,
auditable trigger is worth more than an invisible loop on a laptop that sleeps.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import inbound as inbound_svc
from abm_platform.services import delivery, delivery_gmail

router = APIRouter(prefix="/inbound", tags=["inbound"])


class PollRequest(BaseModel):
    mailbox: str | None = None
    credentials_file: str | None = None
    max_results: int = 100


class SimulateRequest(BaseModel):
    """Raw messages as text — how the suite exercises the path, and how you can
    replay a real bounce you were sent without wiring credentials."""
    messages: list[str]


@router.post("/poll")
def poll(req: PollRequest, db: Session = Depends(get_db)):
    """One polling pass against a real mailbox.

    Requires google-api-python-client and Workspace credentials; returns a
    clear error rather than a stack trace when they are absent, because
    "not configured yet" is the expected state until the domain exists.
    """
    if not req.mailbox or not req.credentials_file:
        return {"ok": False,
                "detail": "mailbox and credentials_file required — "
                          "use /inbound/simulate to exercise the path without them"}
    try:
        fetcher = inbound_svc.gmail_fetcher(
            req.mailbox, req.credentials_file, req.max_results)
        return {"ok": True, "counts": inbound_svc.poll_once(db, fetcher)}
    except ImportError as exc:
        return {"ok": False, "detail": f"Gmail client libraries missing: {exc}"}
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the API
        return {"ok": False, "detail": str(exc)}


@router.post("/simulate")
def simulate(req: SimulateRequest, db: Session = Depends(get_db)):
    """Process supplied raw messages through the identical code path as /poll."""
    items = [(f"sim-{i}", m.encode("utf-8", errors="replace"))
             for i, m in enumerate(req.messages)]
    return {"ok": True, "counts": inbound_svc.poll_once(db, lambda: items)}


@router.get("/transports")
def transports():
    """What can actually send right now.

    `dry_run` alone means no mail can leave — the safe default. Anything else
    requires an explicit env opt-in, so this doubles as a pre-flight check
    before a campaign.
    """
    status = delivery_gmail.register_all()
    registered = sorted(delivery._TRANSPORTS.keys())
    return {
        "registered": registered,
        "can_send_real_mail": registered != ["dry_run"],
        "attempts": status,
        "note": ("SES/Mandrill adapters exist but their AUPs prohibit cold "
                 "outreach — see delivery_gmail.py"),
    }
