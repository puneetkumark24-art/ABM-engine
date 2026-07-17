"""AI Decision Engine — the capability neither HubSpot nor Mailchimp ships.

Instead of static "wait 3 days then Email B", every next touchpoint is chosen
dynamically from the prospect's live state: engagement history, web behaviour,
signal strength at the account, buying-stage estimate, tier, channel history
and content performance. Every decision is LOGGED WITH ITS FULL REASONING
(DecisionLog) — autonomy without explainability is not allowed here.

Design: a deterministic, auditable policy (v1) with a pluggable model hook —
the same pattern as ai_gen: the offline policy works today with zero API keys;
an LLM/ML policy can be registered later behind decide().

Hard stops preserved no matter what the policy says:
  - compliance gates (consent/suppression/do-not-contact/hold) are re-checked;
  - c-suite => hold_human, always;
  - executing a send still goes through the dry-run-only delivery engine.

The feedback loop (VariantPerformance) closes the learning circle: sends →
opens/clicks/replies/meetings per variant → rolling score → choose_variant()
is epsilon-greedy, so better subjects/CTAs/timings win over time.
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_p10 as p10
import models_p11 as p11
from sequences import engine as seq_engine
from abm_platform.events import Event, publish

_POLICY = None          # pluggable: fn(features) -> (action, channel, wait_h, hint, conf, reasons)


def register_policy(fn) -> None:
    global _POLICY
    _POLICY = fn


# ── feature assembly ─────────────────────────────────────────
def build_features(db: Session, person_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    person = db.get(models.Person, person_id)
    org_id = person.current_org_id if person else None

    pe = db.query(p10.PersonEngagement).filter_by(person_id=person_id).first()
    engagement = pe.engagement_score if pe else 0.0
    clicks = pe.clicks if pe else 0

    # recency of last positive event
    msgs = db.query(mx.EmailMessage).filter_by(person_id=person_id).all()
    ids = [m.id for m in msgs]
    last_click = None
    if ids:
        ev = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.message_id.in_(ids),
                      mx.DeliveryEvent.event_type == "click")
              .order_by(mx.DeliveryEvent.occurred_at.desc()).first())
        last_click = ev.occurred_at if ev else None

    # web intent: pricing views / downloads are strong buying-stage markers
    web = db.query(p11.WebEvent).filter_by(person_id=person_id).all()
    pricing_views = sum(1 for w in web if w.event_type == "pricing_view")
    downloads = sum(1 for w in web if w.event_type == "download")

    # account context
    acct = db.get(models.AccountIntelligence, org_id) if org_id else None
    sigs = (db.query(models.Signal).filter_by(org_id=org_id).all()) if org_id else []
    live_high = sum(1 for s in sigs
                    if (s.urgency or "") in ("CRITICAL", "HIGH")
                    and not (s.decay_expires_at and s.decay_expires_at < now))

    # channel history
    li_ok = bool(person and person.linkedin_url)
    email_ok = bool(person and person.primary_email)
    wa_ok = bool(person and (person.whatsapp or person.mobile))

    # buying-stage estimate (heuristic ladder)
    if pricing_views > 0 or (person and person.replied):
        stage = "evaluation"
    elif downloads > 0 or clicks > 0:
        stage = "consideration"
    elif engagement > 0:
        stage = "awareness"
    else:
        stage = "unaware"

    return {
        "person_id": person_id, "org_id": org_id,
        "tier": (acct.priority if acct else None) or (person.tier if person else "COLD"),
        "engagement": engagement, "clicks": clicks,
        "pricing_views": pricing_views, "downloads": downloads,
        "live_high_signals": live_high, "buying_stage": stage,
        "replied": bool(person and person.replied),
        "c_suite": bool(person and (person.seniority_level or "") == "c_suite"),
        "channels": {"email": email_ok, "linkedin": li_ok, "whatsapp": wa_ok},
        "hours_since_click": ((now - last_click).total_seconds() / 3600
                              if last_click else None),
    }


# ── the v1 policy (deterministic, ranked rules, explainable) ─
def _offline_policy(f: dict):
    reasons = []
    if f["replied"]:
        reasons.append("prospect replied — machine steps back (account-centric rule)")
        return ("notify_sales", None, 0, "handoff", 0.95, reasons)
    if f["c_suite"]:
        reasons.append("c-suite persona — human review mandatory (hard stop)")
        return ("hold_human", None, 0, "draft for human review", 0.9, reasons)
    if f["pricing_views"] > 0:
        reasons.append(f"viewed pricing {f['pricing_views']}x — evaluation stage")
        reasons.append("high-intent moment: propose a meeting, don't drip")
        return ("suggest_meeting", "email", 2, "meeting CTA referencing pricing interest", 0.85, reasons)
    if f["hours_since_click"] is not None and f["hours_since_click"] < 24:
        reasons.append(f"clicked {f['hours_since_click']:.0f}h ago — strike while warm")
        return ("send_email", "email", 4, "follow the clicked topic, add case study", 0.8, reasons)
    if f["live_high_signals"] > 0 and f["tier"] == "HOT":
        reasons.append(f"{f['live_high_signals']} live high-urgency signal(s) at a HOT account")
        return ("send_email", "email", 0, "signal-triggered why-now angle", 0.75, reasons)
    if f["engagement"] == 0 and f["channels"]["linkedin"]:
        reasons.append("zero email engagement — switch channel to LinkedIn")
        return ("linkedin_touch", "linkedin", 24, "soft connect referencing role", 0.6, reasons)
    if f["buying_stage"] == "consideration":
        reasons.append("consideration stage (downloads/clicks) — nurture with depth")
        return ("send_email", "email", 48, "whitepaper/deep-dive content", 0.65, reasons)
    reasons.append(f"stage={f['buying_stage']}, tier={f['tier']} — standard cadence")
    return ("wait", None, 72, "hold standard cadence", 0.5, reasons)


def decide(db: Session, person_id: str, now: datetime | None = None) -> p11.DecisionLog:
    """The core call: features -> policy -> gated, logged decision."""
    now = now or datetime.utcnow()
    f = build_features(db, person_id, now)

    # compliance pre-emption: gates override any policy output
    person = db.get(models.Person, person_id)
    ok, reason = seq_engine.is_contactable(person)
    if not ok and reason != "already_replied":
        action, channel, wait_h, hint, conf = "wait", None, 0, "blocked", 1.0
        reasons = [f"compliance gate: {reason} — no outreach permitted"]
    else:
        fn = _POLICY or _offline_policy
        action, channel, wait_h, hint, conf, reasons = fn(f)
        if f["c_suite"] and action in ("send_email", "linkedin_touch", "whatsapp"):
            action, channel = "hold_human", None
            reasons.append("OVERRIDE: c-suite hard stop applied")

    dec = p11.DecisionLog(person_id=person_id, org_id=f["org_id"], action=action,
                          channel=channel, wait_hours=wait_h, content_hint=hint,
                          confidence=conf, reasons=reasons, inputs=f)
    db.add(dec); db.commit()
    publish(Event("decision.made", key=person_id,
                  payload={"action": action, "confidence": conf}))
    return dec


def apply_decision(db: Session, decision_id: str) -> dict:
    """Execute a decision against the sequence engine: reschedules/reroutes the
    person's next touch instead of the static cadence. Sends still only happen
    via the (dry-run) orchestrator/delivery path."""
    dec = db.get(p11.DecisionLog, decision_id)
    if dec is None:
        return {"error": "decision not found"}
    enr = (db.query(models.SequenceEnrollment)
           .filter_by(person_id=dec.person_id, status="ACTIVE").first())
    result = {"action": dec.action}
    if dec.action in ("send_email", "linkedin_touch", "suggest_meeting") and enr:
        enr.next_run_at = datetime.utcnow() + timedelta(hours=dec.wait_hours or 0)
        result["rescheduled_next_run"] = str(enr.next_run_at)
    elif dec.action == "wait" and enr:
        enr.next_run_at = datetime.utcnow() + timedelta(hours=max(dec.wait_hours or 72, 1))
        result["deferred_to"] = str(enr.next_run_at)
    elif dec.action == "notify_sales":
        from . import notification
        n = notification.send(db, "Puneet", "handoff",
                              payload={"person_id": dec.person_id,
                                       "reasons": dec.reasons}, priority="urgent")
        result["notification"] = n.id
    elif dec.action == "hold_human":
        from . import notification
        n = notification.send(db, "Puneet", "approval",
                              payload={"person_id": dec.person_id,
                                       "hint": dec.content_hint}, priority="high")
        result["notification"] = n.id
    dec.executed = True
    db.commit()
    return result


# ── AI feedback loop (VariantPerformance, epsilon-greedy) ────
REPLY_W, MEETING_W, CLICK_W, OPEN_W = 10.0, 20.0, 3.0, 1.0
EPSILON = 0.15   # exploration rate


def record_outcome(db: Session, kind: str, variant_key: str, label: str = "",
                   sends: int = 0, opens: int = 0, clicks: int = 0,
                   replies: int = 0, meetings: int = 0) -> p11.VariantPerformance:
    vp = (db.query(p11.VariantPerformance)
          .filter_by(kind=kind, variant_key=variant_key).first())
    if vp is None:
        vp = p11.VariantPerformance(kind=kind, variant_key=variant_key, label=label,
                                    sends=0, opens=0, clicks=0, replies=0, meetings=0)
        db.add(vp)
    vp.sends = (vp.sends or 0) + sends; vp.opens = (vp.opens or 0) + opens
    vp.clicks = (vp.clicks or 0) + clicks
    vp.replies = (vp.replies or 0) + replies; vp.meetings = (vp.meetings or 0) + meetings
    denom = max(vp.sends, 1)
    vp.score = round((vp.opens * OPEN_W + vp.clicks * CLICK_W
                      + vp.replies * REPLY_W + vp.meetings * MEETING_W) / denom, 4)
    db.commit()
    return vp


def choose_variant(db: Session, kind: str, rng: random.Random | None = None) -> p11.VariantPerformance | None:
    """Epsilon-greedy: mostly exploit the best-scoring variant, sometimes
    explore — this is how 'AI learns → better subject → better CTA' happens."""
    rng = rng or random
    variants = (db.query(p11.VariantPerformance).filter_by(kind=kind)
                .order_by(p11.VariantPerformance.score.desc()).all())
    if not variants:
        return None
    if len(variants) > 1 and rng.random() < EPSILON:
        return rng.choice(variants[1:])   # explore a non-best
    return variants[0]                     # exploit the winner


def learn_from_campaign(db: Session, campaign_id: str) -> dict:
    """Fold a campaign's per-variant results into VariantPerformance."""
    msgs = db.query(mx.EmailMessage).filter_by(campaign_id=campaign_id).all()
    ids = [m.id for m in msgs]
    events = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.message_id.in_(ids)).all()) if ids else []
    ev_by_msg: dict[str, set] = {}
    for e in events:
        ev_by_msg.setdefault(e.message_id, set()).add(e.event_type)
    per: dict[str, dict] = {}
    for m in msgs:
        v = per.setdefault(m.variant or "A", {"sends": 0, "opens": 0, "clicks": 0, "replies": 0})
        v["sends"] += 1
        evs = ev_by_msg.get(m.id, set())
        v["opens"] += 1 if "open" in evs else 0
        v["clicks"] += 1 if "click" in evs else 0
        v["replies"] += 1 if m.status == "replied" else 0
    for name, stats in per.items():
        record_outcome(db, "email", f"campaign:{campaign_id}:variant:{name}",
                       label=name, **stats)
    return per
