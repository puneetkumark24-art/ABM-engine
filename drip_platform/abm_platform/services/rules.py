"""Module 15 — Rules Engine: no-code IF/THEN core.
RUL-001: conditions are pure/deterministic. RUL-002: actions run in order with
per-action results. RUL-003: priority resolves conflicts. RUL-005: outreach
actions still pass compliance gates (enroll goes through the sequence engine's
gate — rules cannot bypass it)."""
from __future__ import annotations
from sqlalchemy.orm import Session
import models
import models_ext as mx
from abm_platform.events import Event, publish

_OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "gt": lambda a, b: (a if a is not None else 0) > b,
    "gte": lambda a, b: (a if a is not None else 0) >= b,
    "lt": lambda a, b: (a if a is not None else 0) < b,
    "lte": lambda a, b: (a if a is not None else 0) <= b,
    "contains": lambda a, b: str(b).lower() in str(a or "").lower(),
    "exists": lambda a, b: a is not None and a != "",
}


def create_rule(db: Session, name: str, event_type: str, conditions: list[dict],
                actions: list[dict], priority: int = 100) -> mx.Rule:
    r = mx.Rule(name=name, trigger="event", event_type=event_type,
                conditions=conditions, actions=actions, priority=priority, status="draft")
    db.add(r); db.commit()
    return r


def activate(db: Session, rule_id: str) -> mx.Rule:
    r = db.get(mx.Rule, rule_id)
    _validate(r)
    r.status = "active"; db.commit()
    return r


def _validate(rule: mx.Rule) -> None:
    for c in (rule.conditions or []):
        if c.get("op", "eq") not in _OPS:
            raise ValueError(f"unknown op {c.get('op')}")
    for a in (rule.actions or []):
        if a.get("action") not in _ACTIONS:
            raise ValueError(f"unknown action {a.get('action')}")


def matches(rule: mx.Rule, subject: dict) -> bool:
    """RUL-001 — pure AND evaluation over a subject dict."""
    for c in (rule.conditions or []):
        op = _OPS[c.get("op", "eq")]
        if not op(subject.get(c.get("field")), c.get("value")):
            return False
    return True


# ---------- action catalog (RUL-005: compliance stays inside the actions) ----------
def _act_publish_event(db, subject, params):
    publish(Event(params.get("event_type", "rule.custom"), key=subject.get("id"), payload=subject))
    return {"published": params.get("event_type")}


def _act_create_task(db, subject, params):
    a = models.ActivityLog(activity_type="task", org_id=subject.get("org_id"),
                           person_id=subject.get("person_id"),
                           owner=params.get("owner", "Puneet"),
                           notes=params.get("note", "rule-created task"),
                           next_action=params.get("next_action"))
    db.add(a); db.flush()
    return {"task": a.id}


def _act_notify(db, subject, params):
    from . import notification
    n = notification.send(db, user=params.get("user", "Puneet"),
                          kind=params.get("kind", "rule"),
                          payload={"subject": subject.get("id"), "note": params.get("note")},
                          priority=params.get("priority", "med"))
    return {"notification": n.id}


def _act_enroll_sequence(db, subject, params):
    """Goes through the sequence engine — the compliance gate CANNOT be bypassed."""
    from sequences import engine as seq_engine
    pid = subject.get("person_id") or subject.get("id")
    enr, reason = seq_engine.enroll_person(db, pid, params.get("sequence_id"))
    return {"enrolled": bool(enr), "reason": reason}


def _act_create_opportunity(db, subject, params):
    o = models.Opportunity(org_id=subject.get("org_id") or subject.get("id"),
                           stage=params.get("stage", "Identified"),
                           probability=params.get("probability", 10),
                           notes=params.get("note", "rule-created"))
    db.add(o); db.flush()
    return {"opportunity": o.id}


_ACTIONS = {
    "publish_event": _act_publish_event,
    "create_task": _act_create_task,
    "notify": _act_notify,
    "enroll_sequence": _act_enroll_sequence,
    "create_opportunity": _act_create_opportunity,
}


def fire(db: Session, event_type: str, subject: dict, dry_run: bool = False) -> list[mx.RuleFiring]:
    """Evaluate all ACTIVE rules for this event type, highest priority first
    (RUL-003). dry_run evaluates without executing actions (simulate)."""
    rules = (db.query(mx.Rule)
             .filter_by(status="active", event_type=event_type)
             .order_by(mx.Rule.priority.desc()).all())
    firings: list[mx.RuleFiring] = []
    for r in rules:
        matched = matches(r, subject)
        results = []
        if matched and not dry_run:
            for a in (r.actions or []):           # RUL-002: ordered
                fn = _ACTIONS[a["action"]]
                try:
                    results.append({a["action"]: fn(db, subject, a.get("params", {}))})
                except Exception as e:
                    results.append({a["action"]: {"error": str(e)}})
        f = mx.RuleFiring(rule_id=r.id, subject_type=subject.get("_type", "unknown"),
                          subject_id=subject.get("id"), matched=matched,
                          actions_result=results, dry_run=dry_run)
        db.add(f); firings.append(f)
    db.commit()
    return firings
