"""
custom_objects.py — Sprint 2: dynamic custom OBJECT types (audit gap CRM 1/10).

Define new object types at runtime (schema = typed field defs), then CRUD
records validated against that schema. Mirrors HubSpot custom objects.

Field types: text, number, date, bool, enum(options), ref (id string).
Validation is strict: required fields enforced, unknown fields rejected, types
checked. All records are tenant-scoped (RLS + GUC default).
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models_crm2 as m2

_TYPES = {"text", "number", "date", "bool", "enum", "ref"}


def define_object(db: Session, key: str, label: str, schema: list[dict],
                  plural_label: str | None = None) -> m2.CustomObjectDef:
    if not key.replace("_", "").isalnum():
        raise ValueError("object key must be snake_case alphanumeric")
    for f in schema:
        if "key" not in f or "type" not in f:
            raise ValueError("each field needs key + type")
        if f["type"] not in _TYPES:
            raise ValueError(f"unknown field type {f['type']}")
        if f["type"] == "enum" and not f.get("options"):
            raise ValueError(f"enum field {f['key']} needs options")
    existing = db.query(m2.CustomObjectDef).filter_by(key=key).first()
    if existing:
        existing.label = label
        existing.plural_label = plural_label or existing.plural_label
        existing.schema = schema
        db.commit()
        return existing
    obj = m2.CustomObjectDef(key=key, label=label, plural_label=plural_label or (label + "s"),
                             schema=schema)
    db.add(obj); db.commit()
    return obj


def _validate(schema: list[dict], data: dict, partial: bool = False) -> dict:
    field_map = {f["key"]: f for f in schema}
    # unknown fields rejected
    for k in data:
        if k not in field_map:
            raise ValueError(f"unknown field '{k}' for this object")
    clean = {}
    for f in schema:
        k, t = f["key"], f["type"]
        if k not in data:
            if f.get("required") and not partial:
                raise ValueError(f"missing required field '{k}'")
            continue
        v = data[k]
        if v is None:
            clean[k] = None
            continue
        if t == "number":
            clean[k] = float(v)
        elif t == "bool":
            clean[k] = bool(v)
        elif t == "date":
            datetime.fromisoformat(str(v)); clean[k] = str(v)
        elif t == "enum":
            if str(v) not in [str(o) for o in f.get("options", [])]:
                raise ValueError(f"'{v}' not in options for '{k}'")
            clean[k] = str(v)
        else:  # text / ref
            clean[k] = str(v)
    return clean


def create_record(db: Session, object_key: str, data: dict) -> m2.CustomObjectRecord:
    obj = db.query(m2.CustomObjectDef).filter_by(key=object_key).first()
    if obj is None:
        raise ValueError(f"unknown object type '{object_key}'")
    clean = _validate(obj.schema or [], data)
    rec = m2.CustomObjectRecord(object_key=object_key, data=clean)
    db.add(rec); db.commit()
    return rec


def update_record(db: Session, record_id: str, data: dict) -> m2.CustomObjectRecord:
    rec = db.get(m2.CustomObjectRecord, record_id)
    if rec is None:
        raise ValueError("record not found")
    obj = db.query(m2.CustomObjectDef).filter_by(key=rec.object_key).first()
    clean = _validate(obj.schema or [], data, partial=True)
    merged = dict(rec.data or {}); merged.update(clean)
    rec.data = merged
    db.commit()
    return rec


def list_records(db: Session, object_key: str, limit: int = 100) -> list[m2.CustomObjectRecord]:
    return (db.query(m2.CustomObjectRecord).filter_by(object_key=object_key)
            .order_by(m2.CustomObjectRecord.created_at.desc()).limit(limit).all())


def delete_record(db: Session, record_id: str) -> bool:
    rec = db.get(m2.CustomObjectRecord, record_id)
    if rec is None:
        return False
    db.delete(rec); db.commit()
    return True
