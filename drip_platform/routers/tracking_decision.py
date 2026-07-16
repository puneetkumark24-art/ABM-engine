"""routers/tracking_decision.py — Phase 11: the public tracking endpoints
(pixel, click redirect, tracking.js, web-event beacon) + the AI Decision
Engine + deliverability surfaces.

The /t/* endpoints are the ones that must eventually be on a PUBLIC HTTPS
domain (they're what recipients' mail clients and browsers hit)."""
from __future__ import annotations

import json
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import tracking, deliverability, decision

router = APIRouter(tags=["tracking-decision"])


# ── public tracking endpoints (/t/*) ─────────────────────────
@router.get("/t/o/{message_id}.gif")
def pixel(message_id: str, request: Request, db: Session = Depends(get_db)):
    """The 1x1 open pixel."""
    tracking.record_open(db, message_id, meta={
        "ip": request.client.host if request.client else None,
        "ua": request.headers.get("user-agent", "")[:200]})
    return Response(content=tracking.PIXEL_GIF, media_type="image/gif",
                    headers={"Cache-Control": "no-store, max-age=0"})


@router.get("/t/c/{token}")
def click(token: str, request: Request, db: Session = Depends(get_db)):
    """Click redirect: log, set visitor cookie, 302 to the real URL + UTM."""
    visitor_id = request.cookies.get("drip_vid")
    url = tracking.record_click(db, token, visitor_id=visitor_id, meta={
        "ip": request.client.host if request.client else None})
    if url is None:
        raise HTTPException(status_code=404, detail="unknown link")
    resp = RedirectResponse(url=url, status_code=302)
    if not visitor_id:
        import uuid as _u
        resp.set_cookie("drip_vid", f"v-{_u.uuid4().hex[:16]}",
                        max_age=31536000, samesite="lax")
    return resp


@router.get("/t/js", response_class=PlainTextResponse)
def tracking_js():
    """The landing-page tracking script (Google-Analytics-style)."""
    return PlainTextResponse(tracking.TRACKING_JS, media_type="application/javascript")


@router.post("/t/e")
async def web_event(request: Request, db: Session = Depends(get_db)):
    """sendBeacon target for tracking.js events."""
    try:
        body = json.loads((await request.body()) or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="bad beacon payload")
    if not body.get("visitor_id") or not body.get("event_type"):
        raise HTTPException(status_code=422, detail="visitor_id and event_type required")
    ev = tracking.record_web_event(db, body["visitor_id"], body["event_type"],
                                   url=body.get("url", ""), props=body.get("props"),
                                   utm=body.get("utm"))
    return {"ok": True, "identified": ev.person_id is not None}


class IdentifyReq(BaseModel):
    visitor_id: str
    person_id: str


@router.post("/t/identify")
def identify(req: IdentifyReq, db: Session = Depends(get_db)):
    n = tracking.identify_visitor(db, req.visitor_id, req.person_id)
    return {"linked_events": n}


# ── deliverability ───────────────────────────────────────────
@router.get("/deliverability/rates")
def rates(campaign_id: Optional[str] = None, db: Session = Depends(get_db)):
    return deliverability.rate_card(db, campaign_id)


@router.get("/deliverability/domains/{domain}")
def domain_health(domain: str, db: Session = Depends(get_db)):
    d = deliverability.update_reputation(db, domain)
    ok, why = deliverability.can_send(db, domain)
    return {"domain": d.domain, "reputation": d.reputation,
            "warmup_stage": d.warmup_stage, "bounce_rate": d.bounce_rate,
            "complaint_rate": d.complaint_rate, "can_send": ok, "gate": why}


# ── AI Decision Engine ───────────────────────────────────────
@router.post("/decide/{person_id}")
def decide(person_id: str, db: Session = Depends(get_db)):
    dec = decision.decide(db, person_id)
    return {"decision_id": dec.id, "action": dec.action, "channel": dec.channel,
            "wait_hours": dec.wait_hours, "content_hint": dec.content_hint,
            "confidence": dec.confidence, "reasons": dec.reasons}


@router.post("/decide/{decision_id}/apply")
def apply(decision_id: str, db: Session = Depends(get_db)):
    return decision.apply_decision(db, decision_id)


@router.get("/decide/variants/{kind}")
def variants(kind: str, db: Session = Depends(get_db)):
    best = decision.choose_variant(db, kind)
    return {"chosen": best.variant_key if best else None,
            "score": best.score if best else None}


@router.post("/decide/learn/{campaign_id}")
def learn(campaign_id: str, db: Session = Depends(get_db)):
    return decision.learn_from_campaign(db, campaign_id)
