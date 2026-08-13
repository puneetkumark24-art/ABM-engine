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
import models_p11 as p11
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
def _person_label(db: Session, person_id: str) -> str | None:
    p = db.get(models.Person, person_id) if person_id else None
    return getattr(p, "full_name", None)


def _person_org(db: Session, person_id: str) -> str | None:
    p = db.get(models.Person, person_id) if person_id else None
    if p is None or not p.current_org_id:
        return None
    org = db.get(models.Organization, p.current_org_id)
    return getattr(org, "canonical_name", None)


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
        # Name and account, not just the id. The dashboard rendered
        # `person_id.slice(0,8)` -- a truncated UUID -- because that was the
        # only identifying field this payload carried.
        "hot_leads": [{"person_id": h.person_id,
                       "name": _person_label(db, h.person_id),
                       "org": _person_org(db, h.person_id),
                       "score": h.engagement_score} for h in hot],
        "active_journey_enrollments": active_journeys,
        "email": {"sends": email["totals"]["sent"], "open_rate": email["rates"]["open_rate"],
                  "click_rate": email["rates"]["click_rate"]},
        "tasks_open": db.query(__import__("models_p12").CrmTask)
                        .filter(__import__("models_p12").CrmTask.status != "done").count(),
        "suppressions": db.query(mx.Suppression).count(),
    }


def growth_operations(db: Session, now: datetime | None = None) -> dict:
    """One operational truth across ABM, marketing automation and CRM."""
    now = now or datetime.utcnow()
    week_ago = now - timedelta(days=7)
    PersonEngagement = p10.PersonEngagement
    CrmTask = __import__("models_p12").CrmTask
    return {
        "mode": "shadow_dry_run",
        "flow": {
            "accounts_monitored": db.query(models.Organization).count(),
            "signals_7d": db.query(models.Signal).filter(models.Signal.created_at >= week_ago).count(),
            "contactable_people": db.query(models.Person).filter(
                models.Person.is_active == True, models.Person.do_not_contact == False,  # noqa: E712
                models.Person.primary_email.isnot(None),
                or_(models.Person.consent_status.is_(None),
                    ~models.Person.consent_status.in_(["denied", "withdrawn"])),
                ~models.Person.primary_email.in_(db.query(mx.Suppression.email))).count(),
            "active_nurture": (db.query(m3.JourneyEnrollment).filter_by(status="active").count()
                               + db.query(models.SequenceEnrollment).filter_by(status="ACTIVE").count()),
            "engaged_people": db.query(PersonEngagement).filter(
                PersonEngagement.engagement_score > 0).count(),
            "open_deals": db.query(models.Opportunity).filter(
                models.Opportunity.closed_at.is_(None)).count(),
        },
        "queues": {
            "draft_approvals": db.query(models.Draft).filter_by(status="pending").count(),
            "campaign_approvals": db.query(models.Draft).filter(
                models.Draft.status == "pending", models.Draft.source.like("campaign:%")).count(),
            "tasks_open": db.query(CrmTask).filter(CrmTask.status != "done").count(),
            "failed_delivery": db.query(mx.SendRequest).filter_by(status="failed").count(),
        },
        "marketing": {
            "campaigns": db.query(mx.EmailCampaign).count(),
            "campaigns_active": db.query(mx.EmailCampaign).filter(
                mx.EmailCampaign.status.in_(["scheduled", "sending", "awaiting_approval"])).count(),
            "journeys": db.query(m3.JourneyDef).count(),
            "journey_enrollments_active": db.query(m3.JourneyEnrollment).filter_by(status="active").count(),
            "messages": db.query(mx.EmailMessage).count(),
            "suppressed": db.query(mx.Suppression).count(),
        },
        "controls": {
            "real_delivery_enabled": False,
            "c_suite_human_gate": True,
            "consent_gate": True,
            "account_rescore_on_touch": True,
        },
    }


# ── email analytics ──────────────────────────────────────────
_EV = ("accepted", "delivered", "simulated_delivered", "open", "click",
       "soft_bounce", "hard_bounce", "rejected", "failed", "complaint",
       "unsubscribe", "reply")


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

    from .email_events import normalize
    counts = {k: 0 for k in _EV}
    uniq: dict[str, set] = {k: set() for k in _EV}
    for e in events:
        et = normalize(e.event_type)
        if et in counts:
            counts[et] += 1
            uniq[et].add(e.message_id)

    accepted = len(uniq["accepted"])
    delivered = len(uniq["delivered"])
    simulated = len(uniq["simulated_delivered"])
    u_open, u_click = len(uniq["open"]), len(uniq["click"])

    def rate(n, d):
        return round(100 * n / d, 2) if d else 0.0

    per_campaign = []
    if not campaign_id:
        for c in db.query(mx.EmailCampaign).all():
            cm = [m for m in messages if m.campaign_id == c.id]
            cm_ids = {m.id for m in cm}
            ce = [e for e in events if e.message_id in cm_ids]
            cev = [(e, normalize(e.event_type)) for e in ce]
            cuniq = lambda kind: len({e.message_id for e, et in cev if et == kind})
            copen, cclick = cuniq("open"), cuniq("click")
            cdelivered = cuniq("delivered")
            csoft, chard = cuniq("soft_bounce"), cuniq("hard_bounce")
            if cm:
                per_campaign.append({"campaign_id": c.id, "campaign": c.name,
                                     "status": c.status, "sent": len(cm),
                                     "delivered": cdelivered,
                                     "unique_opens": copen, "unique_clicks": cclick,
                                     "soft_bounces": csoft, "hard_bounces": chard,
                                     "complaints": cuniq("complaint"),
                                     "unsubscribes": cuniq("unsubscribe"),
                                     "open_rate": rate(copen, cdelivered),
                                     "click_rate": rate(cclick, cdelivered),
                                     "ctor": rate(cclick, copen)})

    reqs = (db.query(mx.SendRequest)
            .filter(mx.SendRequest.message_id.in_(msg_ids)).all()) if msg_ids else []
    failed = sum(1 for r in reqs if r.status == "failed")
    blocked = sum(1 for r in reqs if r.status == "blocked")
    soft_bounces, hard_bounces = len(uniq["soft_bounce"]), len(uniq["hard_bounce"])
    top_links = []
    if msg_ids:
        links = (db.query(p11.TrackedLink)
                 .filter(p11.TrackedLink.message_id.in_(msg_ids))
                 .order_by(p11.TrackedLink.clicks.desc()).limit(20).all())
        top_links = [{"url": x.original_url, "clicks": x.clicks or 0,
                      "message_id": x.message_id} for x in links if x.clicks]
    daily: dict[str, dict[str, int]] = {}
    for e in events:
        day = (e.occurred_at or now).date().isoformat()
        bucket = daily.setdefault(day, {"delivered": 0, "opens": 0, "clicks": 0,
                                        "bounces": 0, "unsubscribes": 0})
        et = normalize(e.event_type)
        if et == "delivered": bucket["delivered"] += 1
        elif et == "open": bucket["opens"] += 1
        elif et == "click": bucket["clicks"] += 1
        elif et in ("soft_bounce", "hard_bounce"): bucket["bounces"] += 1
        elif et == "unsubscribe": bucket["unsubscribes"] += 1

    return {
        "window_days": since_days,
        # "empty" must be distinguishable from "we delivered nothing": a fresh
        # install and a campaign that bounced 100% both show zeros otherwise.
        "mode": ("empty" if not sent and not events else
                 "mixed" if simulated and delivered else
                 "simulation" if simulated else "provider_receipts"),
        "totals": {"attempted": sent, "sent": sent, "accepted": accepted,
                   "delivered": delivered, "simulated_delivered": simulated,
                   "opens": counts["open"],
                   "clicks": counts["click"], "unique_opens": u_open,
                   "unique_clicks": u_click, "replies": counts["reply"],
                   "soft_bounces": soft_bounces, "hard_bounces": hard_bounces,
                   "bounces": soft_bounces + hard_bounces,
                   "rejected": len(uniq["rejected"]), "failed": failed,
                   "blocked": blocked, "complaints": len(uniq["complaint"]),
                   "unsubscribes": len(uniq["unsubscribe"])},
        "rates": {"acceptance_rate": rate(accepted, sent),
                  "delivery_rate": rate(delivered, sent),
                  "open_rate": rate(u_open, delivered),
                  "click_rate": rate(u_click, delivered),
                  "ctr": rate(counts["click"], delivered),
                  "ctor": rate(u_click, u_open),
                  "soft_bounce_rate": rate(soft_bounces, sent),
                  "hard_bounce_rate": rate(hard_bounces, sent),
                  "bounce_rate": rate(soft_bounces + hard_bounces, sent),
                  "complaint_rate": rate(len(uniq["complaint"]), delivered),
                  "unsubscribe_rate": rate(len(uniq["unsubscribe"]), delivered)},
        "top_links": top_links,
        "timeline": [{"date": day, **values} for day, values in sorted(daily.items())],
        "notes": {"opens_are_approximate": True,
                  "delivery_requires_provider_receipt": True,
                  "simulation_is_not_real_delivery": True},
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
