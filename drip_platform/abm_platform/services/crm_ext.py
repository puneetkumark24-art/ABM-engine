"""CRM configurability layer (Phase 12) — closes the HubSpot gap the scorecard
flagged: custom properties (with type validation + default values), saved
views (native columns + custom.<key> + engagement pseudo-fields), and a real
Task object with due dates, assignee, reminders and subtasks."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_p10 as p10
import models_p12 as p12

_OBJECT_MODEL = {"person": models.Person, "organization": models.Organization,
                 "opportunity": models.Opportunity}


# ── custom properties ────────────────────────────────────────
def define_property(db: Session, object_type: str, key: str, label: str,
                    data_type: str = "text", options: list | None = None,
                    default_value: str | None = None, required: bool = False) -> p12.PropertyDef:
    if object_type not in _OBJECT_MODEL:
        raise ValueError(f"unknown object_type {object_type}")
    if data_type not in ("text", "number", "date", "bool", "enum"):
        raise ValueError(f"unknown data_type {data_type}")
    if data_type == "enum" and not options:
        raise ValueError("enum property needs options")
    existing = db.query(p12.PropertyDef).filter_by(object_type=object_type, key=key).first()
    if existing:
        return existing
    pd = p12.PropertyDef(object_type=object_type, key=key, label=label,
                         data_type=data_type, options=options or [],
                         default_value=default_value, required=required)
    db.add(pd); db.commit()
    return pd


def _validate_value(pd: p12.PropertyDef, value) -> str:
    if value is None:
        raise ValueError("value required")
    if pd.data_type == "number":
        float(value)                                       # raises if invalid
    elif pd.data_type == "bool":
        if str(value).lower() not in ("true", "false", "1", "0"):
            raise ValueError("bool must be true/false")
    elif pd.data_type == "date":
        datetime.fromisoformat(str(value))                 # raises if invalid
    elif pd.data_type == "enum":
        if str(value) not in [str(o) for o in (pd.options or [])]:
            raise ValueError(f"'{value}' not in options {pd.options}")
    return str(value)


def set_property(db: Session, object_type: str, object_id: str, key: str, value) -> p12.PropertyValue:
    pd = db.query(p12.PropertyDef).filter_by(object_type=object_type, key=key).first()
    if pd is None:
        raise ValueError(f"property {object_type}.{key} not defined")
    sval = _validate_value(pd, value)
    pv = db.query(p12.PropertyValue).filter_by(property_id=pd.id, object_id=object_id).first()
    if pv is None:
        pv = p12.PropertyValue(property_id=pd.id, object_type=object_type,
                               object_id=object_id, value=sval)
        db.add(pv)
    else:
        pv.value = sval
    db.commit()
    return pv


def get_properties(db: Session, object_type: str, object_id: str) -> dict:
    """All custom properties for a record — defaults applied where unset
    (HubSpot 2026 default-property-values behaviour)."""
    defs = db.query(p12.PropertyDef).filter_by(object_type=object_type).all()
    vals = {v.property_id: v.value for v in
            db.query(p12.PropertyValue).filter_by(object_type=object_type,
                                                  object_id=object_id).all()}
    return {d.key: vals.get(d.id, d.default_value) for d in defs}


# ── saved views ──────────────────────────────────────────────
_OPS = {
    "eq": lambda a, b: str(a) == str(b) if a is not None else False,
    "ne": lambda a, b: str(a) != str(b),
    "gt": lambda a, b: (float(a) if a is not None else 0) > float(b),
    "gte": lambda a, b: (float(a) if a is not None else 0) >= float(b),
    "lt": lambda a, b: (float(a) if a is not None else 0) < float(b),
    "lte": lambda a, b: (float(a) if a is not None else 0) <= float(b),
    "contains": lambda a, b: str(b).lower() in str(a or "").lower(),
    "exists": lambda a, b: a not in (None, ""),
    "is_true": lambda a, b: bool(a),
}


def create_view(db: Session, object_type: str, name: str, filters: list[dict],
                sort_by: str | None = None, sort_desc: bool = True) -> p12.SavedView:
    if object_type not in _OBJECT_MODEL:
        raise ValueError(f"unknown object_type {object_type}")
    for f in filters:
        if f.get("op", "eq") not in _OPS:
            raise ValueError(f"unknown op {f.get('op')}")
    v = p12.SavedView(object_type=object_type, name=name, filters=filters,
                      sort_by=sort_by, sort_desc=sort_desc)
    db.add(v); db.commit()
    return v


def _field_value(db: Session, obj, object_type: str, field: str):
    if field.startswith("custom."):
        return get_properties(db, object_type, obj.id).get(field[7:])
    if field == "engagement_score" and object_type == "person":
        pe = db.query(p10.PersonEngagement).filter_by(person_id=obj.id).first()
        return pe.engagement_score if pe else 0.0
    return getattr(obj, field, None)


def run_view(db: Session, view_id: str, limit: int = 100) -> list:
    v = db.get(p12.SavedView, view_id)
    if v is None:
        return []
    model = _OBJECT_MODEL[v.object_type]
    rows = db.query(model).all()
    out = []
    for obj in rows:
        ok = True
        for f in (v.filters or []):
            op = _OPS[f.get("op", "eq")]
            try:
                if not op(_field_value(db, obj, v.object_type, f["field"]), f.get("value")):
                    ok = False; break
            except (ValueError, TypeError):
                ok = False; break
        if ok:
            out.append(obj)
    if v.sort_by:
        out.sort(key=lambda o: (_field_value(db, o, v.object_type, v.sort_by) or 0),
                 reverse=bool(v.sort_desc))
    return out[:limit]


# ── tasks (with subtasks + reminders) ────────────────────────
def create_task(db: Session, title: str, due_at: datetime | None = None,
                assignee: str = "Puneet", priority: str = "med",
                related_type: str | None = None, related_id: str | None = None,
                parent_task_id: str | None = None, notes: str = "",
                reminder_at: datetime | None = None) -> p12.CrmTask:
    if parent_task_id and db.get(p12.CrmTask, parent_task_id) is None:
        raise ValueError("parent task not found")
    t = p12.CrmTask(title=title, due_at=due_at, assignee=assignee,
                    priority=priority, related_type=related_type,
                    related_id=related_id, parent_task_id=parent_task_id,
                    notes=notes, reminder_at=reminder_at)
    db.add(t); db.commit()
    return t


def complete_task(db: Session, task_id: str) -> p12.CrmTask:
    t = db.get(p12.CrmTask, task_id)
    if t:
        t.status = "done"; t.completed_at = datetime.utcnow(); db.commit()
    return t


def my_day(db: Session, assignee: str, now: datetime | None = None) -> dict:
    """The HubSpot task-queue view: overdue / due today / upcoming / reminders."""
    now = now or datetime.utcnow()
    open_tasks = (db.query(p12.CrmTask)
                  .filter_by(assignee=assignee, status="open").all())
    overdue = [t for t in open_tasks if t.due_at and t.due_at < now]
    today = [t for t in open_tasks if t.due_at and t.due_at.date() == now.date()
             and t.due_at >= now]
    reminders = [t for t in open_tasks if t.reminder_at and t.reminder_at <= now]
    upcoming = [t for t in open_tasks if t.due_at and t.due_at.date() > now.date()]

    def brief(ts): return [{"id": t.id, "title": t.title, "due": t.due_at,
                            "priority": t.priority} for t in
                           sorted(ts, key=lambda x: x.due_at or now)]
    return {"overdue": brief(overdue), "due_today": brief(today),
            "reminders_due": brief(reminders), "upcoming": brief(upcoming[:10])}


def subtasks(db: Session, parent_task_id: str) -> list[p12.CrmTask]:
    return db.query(p12.CrmTask).filter_by(parent_task_id=parent_task_id).all()
