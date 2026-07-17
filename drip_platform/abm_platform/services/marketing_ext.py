"""Marketing upgrades (Phase 12) — the Mailchimp capabilities the scorecard
flagged below 7/10: merge-field rendering with fallbacks, campaign scheduling
honored by a tick, A/B auto-winner with statistical significance, test-send,
and engagement-based segments."""
from __future__ import annotations
import math
import re
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_p10 as p10
from . import marketing, delivery
from abm_platform.events import Event, publish

# ── merge-field rendering with fallbacks: {name|there} ───────
_TAG_RE = re.compile(r"\{([a-z_]+)(?:\|([^}]*))?\}")

_FIELD_MAP = {
    "name": lambda p, o: (p.full_name or "").split(" ")[0] if p else None,
    "full_name": lambda p, o: p.full_name if p else None,
    "institution": lambda p, o: o.canonical_name if o else None,
    "role": lambda p, o: p.current_title if p else None,
    "city": lambda p, o: p.city if p else None,
    "sender": lambda p, o: "Puneet Kumar",
}


def render_merge(db: Session, text: str, person: "models.Person | None" = None) -> str:
    """MKT-006: a merge tag never renders literally — value, else fallback,
    else empty. Supports {name}, {name|there}, {institution|your institution}."""
    org = db.get(models.Organization, person.current_org_id) if (person and person.current_org_id) else None

    def _sub(m):
        key, fallback = m.group(1), m.group(2)
        fn = _FIELD_MAP.get(key)
        val = fn(person, org) if fn else None
        return val or (fallback if fallback is not None else "")
    return _TAG_RE.sub(_sub, text or "")


def test_send(db: Session, campaign_id: str, to_email: str = "test@example.invalid") -> dict:
    """Mailchimp's 'send a test': renders merge fields with a sample person and
    dispatches ONE message via dry-run — never counts against the campaign."""
    camp = db.get(mx.EmailCampaign, campaign_id)
    if camp is None:
        return {"error": "campaign not found"}
    sample = db.query(models.Person).filter(models.Person.is_active == True).first()  # noqa: E712
    rendered = render_merge(db, camp.body, sample)
    req = delivery.enqueue(db, message_id=f"test-{campaign_id}-{datetime.utcnow().timestamp()}",
                           to_email=to_email, subject=f"[TEST] {camp.subject}",
                           body=rendered, transport="dry_run")
    return {"status": req.status, "rendered_preview": rendered[:300]}


# ── scheduling ───────────────────────────────────────────────
def schedule_campaign(db: Session, campaign_id: str, at: datetime) -> mx.EmailCampaign:
    camp = db.get(mx.EmailCampaign, campaign_id)
    if camp is None:
        raise ValueError("campaign not found")
    if not marketing.resolve_members(db, camp.audience_id):
        raise ValueError("audience empty at schedule time")     # MKT preflight
    camp.status = "scheduled"
    camp.scheduled_at = at
    db.commit()
    return camp


def run_scheduled(db: Session, now: datetime | None = None,
                  respect_send_window: bool = True) -> dict:
    """The scheduler tick: fire every scheduled campaign whose time has come.
    KSA send window respected (skip, not error) — same discipline as sequences."""
    from sequences.send_window import is_within_send_window
    now = now or datetime.utcnow()
    if respect_send_window:
        allowed, reason = is_within_send_window()
        if not allowed:
            return {"fired": 0, "skipped": f"send window: {reason}"}
    due = (db.query(mx.EmailCampaign)
           .filter(mx.EmailCampaign.status == "scheduled",
                   mx.EmailCampaign.scheduled_at <= now).all())
    results = []
    for camp in due:
        results.append({camp.name: marketing.send_campaign(db, camp.id)})
    return {"fired": len(due), "results": results}


# ── A/B auto-winner with statistical significance ────────────
MIN_SAMPLE_PER_VARIANT = 30
Z_THRESHOLD = 1.96          # 95% confidence, two-proportion z-test


def _two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float:
    """Two-proportion z-statistic (winner significance)."""
    if n1 == 0 or n2 == 0:
        return 0.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-9
    return abs(p1 - p2) / se


def ab_winner(db: Session, campaign_id: str, metric: str = "open") -> dict:
    """MKT-005: auto-select the A/B winner only after minimum sample AND
    statistical significance; otherwise report 'undecided' for a human call.
    Winner is recorded on the campaign's ab_config and fed to the variant
    performance store (decision-engine feedback loop)."""
    camp = db.get(mx.EmailCampaign, campaign_id)
    if camp is None:
        return {"error": "campaign not found"}
    msgs = db.query(mx.EmailMessage).filter_by(campaign_id=campaign_id).all()
    ids = [m.id for m in msgs]
    events = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.message_id.in_(ids),
                      mx.DeliveryEvent.event_type == ("open" if metric == "open" else "click"))
              .all()) if ids else []
    hit_msgs = {e.message_id for e in events}

    stats: dict[str, dict] = {}
    for m in msgs:
        v = stats.setdefault(m.variant or "A", {"sends": 0, "hits": 0})
        v["sends"] += 1
        v["hits"] += 1 if m.id in hit_msgs else 0
    if len(stats) < 2:
        return {"decided": False, "reason": "need >=2 variants", "stats": stats}

    ranked = sorted(stats.items(), key=lambda kv: (kv[1]["hits"] / max(kv[1]["sends"], 1)),
                    reverse=True)
    (best, b), (second, s) = ranked[0], ranked[1]
    if b["sends"] < MIN_SAMPLE_PER_VARIANT or s["sends"] < MIN_SAMPLE_PER_VARIANT:
        return {"decided": False, "reason": f"minimum sample {MIN_SAMPLE_PER_VARIANT}/variant not met",
                "stats": stats}
    z = _two_prop_z(b["hits"], b["sends"], s["hits"], s["sends"])
    if z < Z_THRESHOLD:
        return {"decided": False, "reason": f"not significant (z={z:.2f} < {Z_THRESHOLD})",
                "stats": stats}

    ab = dict(camp.ab_config or {})
    ab["winner"] = best
    ab["decided_at"] = str(datetime.utcnow())
    camp.ab_config = ab
    db.commit()
    # feed the AI feedback loop
    from . import decision
    decision.record_outcome(db, "email", f"campaign:{campaign_id}:winner:{best}",
                            label=best, sends=b["sends"], opens=b["hits"])
    publish(Event("email.ab.winner", key=campaign_id, payload={"winner": best, "z": round(z, 2)}))
    return {"decided": True, "winner": best, "z": round(z, 2), "stats": stats}


# ── engagement-based segments (Mailchimp 'engagement scoring') ─
def resolve_engaged_segment(db: Session, min_engagement: float = 0.1,
                            tier: str | None = None) -> list["models.Person"]:
    """Segment by behaviour, not just fields — requires the Phase-10 rollup."""
    q = (db.query(models.Person)
         .join(p10.PersonEngagement, p10.PersonEngagement.person_id == models.Person.id)
         .filter(models.Person.is_active == True,  # noqa: E712
                 p10.PersonEngagement.engagement_score >= min_engagement))
    if tier:
        q = q.filter(models.Person.tier == tier)
    return q.all()
