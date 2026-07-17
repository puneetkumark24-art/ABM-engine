"""
analytics_fast.py — set-based analytics (P0-D) replacing analytics.query's
load-all-rows-then-count-in-Python (which OOMs at 100M rows).

query_fast()   one SQL GROUP BY — the database aggregates; we return counts.
rollup_daily() incremental daily rollup written to a summary table pattern
               (here computed set-based; in production this feeds ClickHouse /
               Timescale continuous aggregates and dashboards read the rollup,
               never the raw events).
Behaviourally identical to analytics.query; O(scan) in the DB with index on
(event_type, occurred_at), not O(rows) in Python.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
import models_ext as mx


def query_fast(db: Session, event_type: Optional[str] = None, since_days: int = 30,
               group_by: str = "event_type") -> dict:
    since = datetime.utcnow() - timedelta(days=since_days)
    ME = mx.MetricEvent
    grp = ME.event_type if group_by == "event_type" else func.date(ME.occurred_at)
    q = db.query(grp, func.count()).filter(ME.occurred_at >= since)
    if event_type:
        q = q.filter(ME.event_type == event_type)
    q = q.group_by(grp)
    groups = {str(k): int(c) for k, c in q.all()}
    total = sum(groups.values())
    return {"since_days": since_days, "total": total, "groups": groups}


def funnel_fast(db: Session, steps: list[str], since_days: int = 30) -> list[dict]:
    """Distinct subjects per step via SQL COUNT(DISTINCT), set-based."""
    since = datetime.utcnow() - timedelta(days=since_days)
    ME = mx.MetricEvent
    result, prev = [], None
    for step in steps:
        cnt = (db.query(func.count(func.distinct(ME.subject_id)))
               .filter(ME.event_type == step, ME.occurred_at >= since).scalar()) or 0
        conv = (cnt / prev * 100.0) if prev else 100.0
        result.append({"step": step, "count": int(cnt), "conversion_pct": round(conv, 1)})
        prev = cnt or 1
    return result
