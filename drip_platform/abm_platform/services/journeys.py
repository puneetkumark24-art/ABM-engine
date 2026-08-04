"""
journeys.py — Sprint 3: multi-step marketing journey orchestration
(Mailchimp Customer Journeys / Customer.io / Marketo Smart Campaigns parity).

A journey is a graph of nodes:
  send   {id, type:"send", content_blocks:[...], variants?:[...], next}
  wait   {id, type:"wait", hours:N, next}
  branch {id, type:"branch", on:"opened"|"clicked", yes, no}
  exit   {id, type:"exit"}

tick() advances every active enrollment whose next_action_at has arrived,
executing its current node and scheduling the next. Branch decisions read a
signal function (engagement) so the runner is deterministic and testable.

Also provides:
  resolve_content_blocks() — dynamic content (conditional blocks per person)
  pick_variant()          — multivariate (>2) weighted selection
"""
from __future__ import annotations
import random
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_s3 as m3
import models
import models_ext as mx
from . import marketing, marketing_ext, delivery, attribution, engagement

_SEND, _WAIT, _BRANCH, _EXIT = "send", "wait", "branch", "exit"
_NODE_TYPES = {_SEND, _WAIT, _BRANCH, _EXIT}


def define_journey(db: Session, name: str, nodes: list[dict],
                   entry_node_id: str | None = None) -> m3.JourneyDef:
    if not nodes:
        raise ValueError("journey needs at least one node")
    ids = {n.get("id") for n in nodes}
    for n in nodes:
        if "id" not in n or n.get("type") not in _NODE_TYPES:
            raise ValueError(f"each node needs id + valid type {sorted(_NODE_TYPES)}")
        # referential integrity across the graph
        for ref in ("next", "yes", "no"):
            if n.get(ref) and n[ref] not in ids:
                raise ValueError(f"node {n['id']} points to unknown node '{n[ref]}'")
        if n["type"] == _BRANCH and n.get("on") not in ("opened", "clicked"):
            raise ValueError("branch node needs on ∈ opened|clicked")
    entry = entry_node_id or nodes[0]["id"]
    if entry not in ids:
        raise ValueError("entry_node_id not in nodes")
    j = m3.JourneyDef(name=name, nodes=nodes, entry_node_id=entry)
    db.add(j); db.commit()
    return j


def enroll(db: Session, journey_id: str, person_id: str,
           now: datetime | None = None) -> m3.JourneyEnrollment:
    j = db.get(m3.JourneyDef, journey_id)
    if j is None:
        raise ValueError("journey not found")
    person = db.get(models.Person, person_id)
    if person is None:
        raise ValueError("person not found")
    sendable, reason = marketing.is_sendable(db, person)
    if not sendable:
        raise ValueError(f"person is not contactable: {reason}")
    existing = (db.query(m3.JourneyEnrollment)
                .filter_by(journey_id=journey_id, person_id=person_id, status="active")
                .first())
    if existing:
        return existing
    now = now or datetime.utcnow()
    e = m3.JourneyEnrollment(journey_id=journey_id, person_id=person_id,
                             current_node_id=j.entry_node_id, next_action_at=now,
                             history=[])
    db.add(e); db.commit()
    return e


def _node_map(j: m3.JourneyDef) -> dict:
    return {n["id"]: n for n in (j.nodes or [])}


def _message_id(enrollment_id: str, node_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"drip:journey:{enrollment_id}:{node_id}"))


def _engaged(db: Session, enrollment: m3.JourneyEnrollment, node: dict) -> bool:
    wanted = "open" if node.get("on") == "opened" else "click"
    send_nodes = [h.get("node") for h in (enrollment.history or []) if h.get("action") == "send"]
    ids = [_message_id(enrollment.id, n) for n in send_nodes if n]
    return bool(ids and db.query(mx.DeliveryEvent).filter(
        mx.DeliveryEvent.message_id.in_(ids), mx.DeliveryEvent.event_type == wanted).first())


def tick(db: Session, now: datetime | None = None,
         signal=None, max_batch: int = 500) -> dict:
    """Advance due enrollments. `signal(enrollment, node) -> bool` answers branch
    questions (did the person open/click); defaults to False (no engagement)."""
    now = now or datetime.utcnow()
    signal = signal or (lambda e, n: _engaged(db, e, n))
    due = (db.query(m3.JourneyEnrollment)
           .filter(m3.JourneyEnrollment.status == "active",
                   m3.JourneyEnrollment.next_action_at <= now)
           .limit(max_batch).all())
    sent = advanced = completed = blocked = existing = 0
    touched_orgs: set[str] = set()
    for e in due:
        j = db.get(m3.JourneyDef, e.journey_id)
        if j is None or j.status != "active":
            continue
        nodes = _node_map(j)
        guard = 0
        # walk instantaneous nodes (send/branch/exit) until we hit a wait or end
        while e.status == "active" and guard < 50:
            guard += 1
            node = nodes.get(e.current_node_id)
            if node is None:
                e.status = "completed"; completed += 1; break
            t = node["type"]
            hist = list(e.history or [])
            if t == _SEND:
                person = db.get(models.Person, e.person_id)
                ok, reason = marketing.is_sendable(db, person)
                if not ok:
                    hist.append({"at": str(now), "node": node["id"], "action": "blocked",
                                 "reason": reason})
                    e.history = hist; e.status = "exited"; e.current_node_id = None
                    blocked += 1
                    break
                variant = pick_variant(node.get("variants")) if node.get("variants") else None
                mid = _message_id(e.id, node["id"])
                msg = db.get(mx.EmailMessage, mid)
                created = msg is None
                if msg is None:
                    msg = mx.EmailMessage(id=mid, campaign_id=None, person_id=person.id,
                                          to_email=person.primary_email, variant=variant or "control")
                    db.add(msg); db.flush()
                    subject = marketing_ext.render_merge(db, node.get("subject") or j.name, person)
                    raw_body = node.get("body") or node.get("content") or ""
                    body = marketing_ext.render_merge(db, raw_body, person)
                    req = delivery.enqueue(db, message_id=mid, to_email=person.primary_email,
                                           subject=subject, body=body, transport="dry_run")
                    if req.status != "sent":
                        hist.append({"at": str(now), "node": node["id"], "action": "blocked",
                                     "reason": f"delivery_{req.status}"})
                        e.history = hist; e.status = "exited"; e.current_node_id = None
                        blocked += 1
                        break
                    msg.status = "sent"; msg.sent_at = now
                    attribution.record_touch(db, org_id=person.current_org_id,
                                             person_id=person.id, channel="email",
                                             campaign_id=j.id, occurred_at=now)
                    if person.current_org_id:
                        touched_orgs.add(person.current_org_id)
                else:
                    existing += 1
                hist.append({"at": str(now), "node": node["id"], "action": "send",
                             "variant": variant, "message_id": mid})
                e.history = hist
                if created:
                    sent += 1
                nxt = node.get("next")
            elif t == _WAIT:
                hist.append({"at": str(now), "node": node["id"], "action": "wait",
                             "hours": node.get("hours", 0)})
                e.history = hist
                e.next_action_at = now + timedelta(hours=int(node.get("hours", 0)))
                e.current_node_id = node.get("next")
                advanced += 1
                if e.current_node_id is None:
                    e.status = "completed"; completed += 1
                break  # stop instantaneous walk; resume at/after next_action_at
            elif t == _BRANCH:
                took = bool(signal(e, node))
                nxt = node.get("yes") if took else node.get("no")
                hist.append({"at": str(now), "node": node["id"], "action": "branch",
                             "on": node.get("on"), "result": took})
                e.history = hist
            else:  # exit
                e.status = "completed"; completed += 1
                e.current_node_id = None
                break
            if t in (_SEND, _BRANCH):
                if nxt is None:
                    e.status = "completed"; completed += 1
                    e.current_node_id = None
                    break
                e.current_node_id = nxt
        db.add(e)
    db.commit()
    for org_id in touched_orgs:
        engagement.rollup_org(db, org_id)
    return {"processed": len(due), "sends": sent, "advanced": advanced,
            "completed": completed, "blocked": blocked,
            "existing_skipped": existing, "accounts_rescored": len(touched_orgs)}


# ── dynamic content blocks ───────────────────────────────────
def resolve_content_blocks(blocks: list[dict], person: dict) -> list[dict]:
    """Return only blocks whose `if` predicate matches the person attributes.
    A block: {id, html, if?:{field, op, value}}. op ∈ eq|neq|in|gt|lt|exists."""
    out = []
    for b in blocks:
        cond = b.get("if")
        if cond is None:
            out.append(b); continue
        field, op, val = cond.get("field"), cond.get("op", "eq"), cond.get("value")
        pv = person.get(field)
        ok = (
            (op == "eq" and pv == val) or
            (op == "neq" and pv != val) or
            (op == "in" and pv in (val or [])) or
            (op == "gt" and pv is not None and pv > val) or
            (op == "lt" and pv is not None and pv < val) or
            (op == "exists" and pv is not None)
        )
        if ok:
            out.append(b)
    return out


# ── multivariate (>2) weighted selection ─────────────────────
def pick_variant(variants: list[dict], rng: random.Random | None = None) -> str:
    """variants: [{key, weight}]. Returns a key by weighted choice. Supports any
    number of arms (multivariate), unlike a 50/50 A/B split."""
    if not variants:
        return "control"
    rng = rng or random
    total = sum(max(0.0, float(v.get("weight", 1))) for v in variants) or 1.0
    r = rng.random() * total
    acc = 0.0
    for v in variants:
        acc += max(0.0, float(v.get("weight", 1)))
        if r <= acc:
            return v.get("key", "control")
    return variants[-1].get("key", "control")
