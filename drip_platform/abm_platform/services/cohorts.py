"""
cohorts.py — Sprint 7: cohort retention + time-series trends over the
partitioned metric_events firehose (the analytics gap vs Amplitude/HubSpot
reports). Pure-Python aggregation on top of a single indexed read, so it runs
identically on SQLite and PostgreSQL.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_ext as mx


def _events(db: Session, event_types: set[str], since: datetime):
    q = (db.query(mx.MetricEvent.event_type, mx.MetricEvent.subject_id,
                  mx.MetricEvent.occurred_at)
         .filter(mx.MetricEvent.occurred_at >= since,
                 mx.MetricEvent.event_type.in_(event_types)))
    return q.all()


def timeseries(db: Session, event_type: str, since_days: int = 30,
               bucket_days: int = 1, now: datetime | None = None) -> list[dict]:
    """Counts of `event_type` per fixed-width time bucket."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=since_days)
    rows = _events(db, {event_type}, since)
    n_buckets = max(1, (since_days + bucket_days - 1) // bucket_days)
    buckets = [0] * n_buckets
    for _, _sid, occ in rows:
        if occ is None:
            continue
        idx = int((occ - since).days // bucket_days)
        if 0 <= idx < n_buckets:
            buckets[idx] += 1
    return [{"bucket_start": (since + timedelta(days=i * bucket_days)).date().isoformat(),
             "count": c} for i, c in enumerate(buckets)]


def cohort_retention(db: Session, cohort_event: str, return_event: str,
                     period_days: int = 7, periods: int = 4, since_days: int = 90,
                     now: datetime | None = None) -> dict:
    """Classic retention matrix: group subjects by the period of their FIRST
    cohort_event, then measure the share performing return_event in each later
    period. Returns per-cohort size + retention percentages (period 0 = 100%)."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=since_days)
    rows = _events(db, {cohort_event, return_event}, since)

    first_cohort: dict[str, datetime] = {}
    returns: dict[str, list[datetime]] = {}
    for et, sid, occ in rows:
        if sid is None or occ is None:
            continue
        if et == cohort_event:
            if sid not in first_cohort or occ < first_cohort[sid]:
                first_cohort[sid] = occ
        if et == return_event:
            returns.setdefault(sid, []).append(occ)

    def period_index(base: datetime, when: datetime) -> int:
        return int((when - base).days // period_days)

    n_cohorts = max(1, (since_days + period_days - 1) // period_days)
    # cohort_bucket -> {subjects:set, retained:[set per period]}
    cohorts = {i: {"subjects": set(), "retained": [set() for _ in range(periods)]}
               for i in range(n_cohorts)}

    for sid, base in first_cohort.items():
        cb = period_index(since, base)
        if not (0 <= cb < n_cohorts):
            continue
        cohorts[cb]["subjects"].add(sid)
        for when in returns.get(sid, []):
            off = period_index(base, when)
            if 0 <= off < periods:
                cohorts[cb]["retained"][off].add(sid)

    out = []
    for i in range(n_cohorts):
        subs = cohorts[i]["subjects"]
        if not subs:
            continue
        size = len(subs)
        retention = []
        for off in range(periods):
            if off == 0:
                retention.append(100.0)
            else:
                retention.append(round(100 * len(cohorts[i]["retained"][off]) / size, 1))
        out.append({"cohort_start": (since + timedelta(days=i * period_days)).date().isoformat(),
                    "size": size, "retention_pct": retention})
    return {"cohort_event": cohort_event, "return_event": return_event,
            "period_days": period_days, "periods": periods, "cohorts": out}
