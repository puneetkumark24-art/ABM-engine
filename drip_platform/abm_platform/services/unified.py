"""
unified.py — Platform Unification services (U1).

Three cross-module capabilities that make DRIP feel like ONE product:
  • global_search()       — one query across companies, contacts, deals,
                            campaigns, signals, tasks, quotes, products,
                            journeys, workflows, and API keys.
  • executive_dashboard() — the single homepage aggregation: pipeline, accounts,
                            engagement, signals, email, journeys, system.
  • email_analytics()     — Mailchimp/HubSpot-grade email metrics computed from
                            email_messages + delivery_events (sends, delivered,
                            opens, clicks, unique rates, CTR, CTOR, bounces,
                            unsubscribes, per-campaign comparison).
  • ga4_status()/ga4_send_event() — Google Analytics 4 measurement-protocol
                            seam; dry-run until GA4 credentials are configured
                            (BLOCKED-EXTERNAL: needs measurement_id+api_secret).
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

import models
import models_ext as mx
import models_p10 as p10
import models_crm2 as m2
import models_s3 as m3
import models_s8 as m8

try:
    from config import get_secret
except Exception:  # pragma: no cover
    def get_secret(name, default=None):
        import os
        return os.environ.get(name, default)


# ── global search ────────────────────────────────────────────
def _like(col, q):
    return col.ilike(f"%{q}%")


def global_search(db: Session, q: str, limit_per_type: int = 5) -> dict:
    """One search box for everything. Returns grouped, lightweight hits."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"query": q, "results": {}, "total": 0}
    out: dict[str, list] = {}

    def add(kind, rows, fmt):
        hits = [fmt(r) for r in rows]
        if hits:
            out[kind] = hits

    add("companies",
        db.query(models.Organization).filter(or_(
            _like(models.Organization.canonical_name, q))).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.canonical_name, "url": f"/organizations/{r.id}"})
    add("contacts",
        db.query(models.Person).filter(or_(
            _like(models.Person.full_name, q), _like(models.Person.primary_email, q),
            _like(models.Person.current_title, q))).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.full_name, "sub": r.current_title,
                   "url": f"/persons/{r.id}"})
    add("deals",
        db.query(models.Opportunity).filter(or_(
            _like(models.Opportunity.stage, q),
            _like(models.Opportunity.next_step, q),
            _like(models.Opportunity.notes, q))).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": f"deal {r.id[:8]} · {r.stage or 'no stage'}",
                   "sub": r.next_step, "url": f"/opportunities/{r.id}"})
    add("campaigns",
        db.query(mx.EmailCampaign).filter(or_(
            _like(mx.EmailCampaign.name, q),
            _like(mx.EmailCampaign.subject, q))).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.name, "sub": r.status})
    add("signals",
        db.query(models.Signal).filter(or_(
            _like(models.Signal.title, q),
            _like(models.Signal.signal_type, q))).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.title, "sub": r.signal_type})
    add("tasks",
        db.query(__import__("models_p12").CrmTask).filter(
            _like(__import__("models_p12").CrmTask.title, q)).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.title, "sub": r.status})
    add("quotes",
        db.query(m2.Quote).filter(_like(m2.Quote.name, q)).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.name, "sub": r.status, "url": f"/crm/quotes/{r.id}"})
    add("products",
        db.query(m2.Product).filter(or_(
            _like(m2.Product.name, q), _like(m2.Product.sku, q))).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.name, "sub": r.sku})
    add("journeys",
        db.query(m3.JourneyDef).filter(_like(m3.JourneyDef.name, q)).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.name, "sub": r.status})
    add("workflows",
        db.query(mx.WorkflowDef).filter(_like(mx.WorkflowDef.name, q)).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.name, "sub": r.status})
    add("api_keys",
        db.query(m8.ApiKey).filter(_like(m8.ApiKey.name, q)).limit(limit_per_type).all(),
        lambda r: {"id": r.id, "label": r.name, "sub": r.prefix})

    return {"query": q, "results": out,
            "total": sum(len(v) for v in out.values())}


# ── executive dashboard ──────────────────────────────────────
def executive_dashboard(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    week_ago = now - timedelta(days=7)

    open_opps = (db.query(models.Opportunity)
                 .filter(models.Opportunity.closed_at.is_(None)).all())
    pipeline_minor = sum(o.amount_minor or 0 for o in open_opps)

    # weighted via stage links where present
    links = db.query(p10.OpportunityStageLink).all()
    stage_map = {s.id: s for s in db.query(p10.PipelineStage).all()}
    weighted = 0.0
    for ln in links:
        st = stage_map.get(ln.stage_id)
        opp = next((o for o in open_opps if o.id == ln.opportunity_id), None)
        if st and opp and not (st.is_won or st.is_lost):
            weighted += (opp.amount_minor or 0) * (st.probability or 0)

    signals_week = (db.query(models.Signal)
                    .filter(models.Signal.created_at >= week_ago).count())
    hot = (db.query(p10.PersonEngagement)
           .filter(p10.PersonEngagement.engagement_score > 0)
           .order_by(p10.PersonEngagement.engagement_score.desc()).limit(5).all())
    active_journeys = db.query(m3.JourneyEnrollment).filter_by(status="active").count()
    email = email_analytics(db)

    return {
        "as_of": now.isoformat(),
        "accounts": db.query(models.Organization).count(),
        "contacts": db.query(models.Person).count(),
        "open_deals": len(open_opps),
        "pipeline_minor": pipeline_minor,
        "pipeline_sar": f"SAR {pipeline_minor/100:,.0f}",
        "weighted_minor": int(weighted),
        "weighted_sar": f"SAR {weighted/100:,.0f}",
        "signals_this_week": signals_week,
        "hot_leads": [{"person_id": h.person_id, "score": h.engagement_score} for h in hot],
        "active_journey_enrollments": active_journeys,
        "email": {"sends": email["totals"]["sent"], "open_rate": email["rates"]["open_rate"],
                  "click_rate": email["rates"]["click_rate"]},
        "tasks_open": db.query(__import__("models_p12").CrmTask)
                        .filter(__import__("models_p12").CrmTask.status != "done").count(),
        "suppressions": db.query(mx.Suppression).count(),
    }


# ── email analytics ──────────────────────────────────────────
_EV = ("delivered", "open", "click", "bounce", "complaint", "unsubscribe", "reply")


def email_analytics(db: Session, campaign_id: str | None = None,
                    since_days: int = 90, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    since = now - timedelta(days=since_days)

    mq = db.query(mx.EmailMessage)
    if campaign_id:
        mq = mq.filter(mx.EmailMessage.campaign_id == campaign_id)
    messages = mq.all()
    msg_ids = {m.id for m in messages}
    sent = len(messages)

    evq = (db.query(mx.DeliveryEvent)
           .filter(mx.DeliveryEvent.occurred_at >= since))
    events = [e for e in evq.all() if e.message_id in msg_ids] if msg_ids else []

    counts = {k: 0 for k in _EV}
    uniq: dict[str, set] = {k: set() for k in _EV}
    for e in events:
        et = (e.event_type or "").lower()
        for k in _EV:
            if k in et:
                counts[k] += 1
                uniq[k].add(e.message_id)

    delivered = counts["delivered"] or sent  # if no delivery receipts, assume sent
    u_open, u_click = len(uniq["open"]), len(uniq["click"])

    def rate(n, d):
        return round(100 * n / d, 2) if d else 0.0

    per_campaign = []
    if not campaign_id:
        for c in db.query(mx.EmailCampaign).all():
            cm = [m for m in messages if m.campaign_id == c.id]
            cm_ids = {m.id for m in cm}
            ce = [e for e in events if e.message_id in cm_ids]
            copen = len({e.message_id for e in ce if "open" in (e.event_type or "")})
            cclick = len({e.message_id for e in ce if "click" in (e.event_type or "")})
            if cm:
                per_campaign.append({"campaign": c.name, "sent": len(cm),
                                     "unique_opens": copen, "unique_clicks": cclick,
                                     "open_rate": rate(copen, len(cm)),
                                     "click_rate": rate(cclick, len(cm))})

    return {
        "window_days": since_days,
        "totals": {"sent": sent, "delivered": delivered, "opens": counts["open"],
                   "clicks": counts["click"], "unique_opens": u_open,
                   "unique_clicks": u_click, "replies": counts["reply"],
                   "bounces": counts["bounce"], "complaints": counts["complaint"],
                   "unsubscribes": counts["unsubscribe"]},
        "rates": {"delivery_rate": rate(delivered, sent),
                  "open_rate": rate(u_open, delivered),
                  "click_rate": rate(u_click, delivered),
                  "ctr": rate(counts["click"], delivered),
                  "ctor": rate(u_click, u_open),
                  "bounce_rate": rate(counts["bounce"], sent),
                  "unsubscribe_rate": rate(counts["unsubscribe"], delivered)},
        "per_campaign": sorted(per_campaign, key=lambda x: -x["sent"]),
    }


# ── GA4 seam (BLOCKED-EXTERNAL until credentials provided) ───
def ga4_status() -> dict:
    mid = get_secret("GA4_MEASUREMENT_ID", "")
    sec = get_secret("GA4_API_SECRET", "")
    configured = bool(mid and sec)
    return {"configured": configured, "measurement_id": mid or None,
            "mode": "live" if configured else "dry-run",
            "how_to_enable": None if configured else
            "Set GA4_MEASUREMENT_ID and GA4_API_SECRET (GA4 Admin -> Data Streams "
            "-> Measurement Protocol API secrets); events then post to "
            "google-analytics.com/mp/collect."}


def ga4_send_event(client_id: str, name: str, params: dict | None = None) -> dict:
    """Send one event via GA4 Measurement Protocol. Dry-run without credentials
    (returns the payload it WOULD send; never fabricates success)."""
    st = ga4_status()
    payload = {"client_id": client_id, "events": [{"name": name, "params": params or {}}]}
    if not st["configured"]:
        return {"sent": False, "mode": "dry-run", "payload": payload}
    import json
    import urllib.request
    url = (f"https://www.google-analytics.com/mp/collect?"
           f"measurement_id={st['measurement_id']}&api_secret={get_secret('GA4_API_SECRET')}")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"sent": resp.status in (200, 204), "mode": "live", "status": resp.status}
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "mode": "live", "error": str(e)}
