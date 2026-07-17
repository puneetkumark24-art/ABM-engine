"""
scale.py — set-based replacements for the O(N)/O(N^2) hot paths (P0-C).

Each function is behaviorally equivalent to the naive version but pushes the
work into indexed SQL instead of loading whole tables into Python:

  get_due_fast()          replaces sequences.engine.get_due's load-all-then-
                          filter-in-Python with a single 3-table join + LIMIT.
  resolve_segment_fast()  replaces marketing.resolve_members' full person scan
                          with a compiled WHERE (whitelisted fields/ops).
  sendable_person_ids()   replaces per-recipient suppression/consent queries
                          with one set-based NOT EXISTS.
  dedupe_candidates()     replaces enrichment.detect_duplicates' O(N^2) pairwise
                          scan with blocking keys (exact email, and last-name +
                          org) so only same-block pairs are compared — 2.5B ops
                          at 50k collapses to thousands.

All portable across SQLite (dev) and PostgreSQL (prod).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import and_, or_, case, func, exists, select
from sqlalchemy.orm import Session
import models
import models_ext as mx
from sequences.send_window import is_within_send_window

_TIER_RANK = case((models.Person.tier == "HOT", 1),
                  (models.Person.tier == "WARM", 2), else_=3)


def get_due_fast(db: Session, limit: int = 20, now: Optional[datetime] = None,
                 respect_send_window: bool = True) -> list[dict]:
    """One join: enrollment -> its next step -> person, filtered + ordered +
    limited in the database. Same output shape as engine.get_due."""
    now = now or datetime.utcnow()
    if respect_send_window:
        allowed, _ = is_within_send_window()
        if not allowed:
            return []
    E, S, P = models.SequenceEnrollment, models.SequenceStep, models.Person
    q = (db.query(E, S, P)
         .join(S, and_(S.sequence_id == E.sequence_id,
                       S.step_number == E.current_step + 1))
         .join(P, P.id == E.person_id)
         .filter(E.status == "ACTIVE",
                 E.next_run_at.isnot(None), E.next_run_at <= now,
                 P.is_active.is_(True),
                 P.do_not_contact.is_(False),
                 P.replied.is_(False),
                 or_(P.consent_status.is_(None), P.consent_status != "denied"))
         .order_by(_TIER_RANK.asc(), P.priority_score.desc())
         .limit(limit))
    out = []
    for enr, step, person in q.all():
        out.append({"enrollment": enr, "person": person, "next_step": step,
                    "tier_rank": None, "priority_score": person.priority_score or 0})
    return out


_FIELD_WHITELIST = {
    "tier": models.Person.tier, "seniority_level": models.Person.seniority_level,
    "persona": models.Person.persona, "priority_score": models.Person.priority_score,
    "city": models.Person.city, "country": models.Person.country,
    "current_org_id": models.Person.current_org_id,
    "is_indian_origin": models.Person.is_indian_origin,
    "consent_status": models.Person.consent_status,
    "warmness": models.Person.warmness,
}


def resolve_segment_fast(db: Session, definition: list[dict], limit: int = 100000):
    """Compile a dynamic-segment filter list into one indexed query. Only
    whitelisted Person fields are filterable (prevents injection / bad columns)."""
    P = models.Person
    q = db.query(P).filter(P.is_active.is_(True))
    for c in (definition or []):
        col = _FIELD_WHITELIST.get(c.get("field"))
        if col is None:
            continue  # ignore unknown fields (fail safe, never full-scan on junk)
        op, val = c.get("op", "eq"), c.get("value")
        if op == "eq":
            q = q.filter(col == val)
        elif op == "ne":
            q = q.filter(col != val)
        elif op == "gt":
            q = q.filter(col > val)
        elif op == "gte":
            q = q.filter(col >= val)
        elif op == "lt":
            q = q.filter(col < val)
        elif op == "lte":
            q = q.filter(col <= val)
        elif op == "contains":
            q = q.filter(col.ilike(f"%{val}%"))
        elif op == "is_true":
            q = q.filter(col.is_(True))
        elif op == "is_false":
            q = q.filter(or_(col.is_(False), col.is_(None)))
    return q.limit(limit).all()


def resolve_segment_cached(db: Session, audience_id: str, definition: list[dict],
                           ttl: int = 120) -> list[str]:
    """Cached dynamic-segment membership (Gap-3). Dynamic segments are recomputed
    on every campaign/journey enrollment; caching the id set for a short TTL cuts
    repeated full evaluations. Cache invalidated on the audience's definition
    change (caller invalidates)."""
    from . import cache
    hit = cache.get_cached_segment(audience_id)
    if hit is not None:
        return hit
    ids = [p.id for p in resolve_segment_fast(db, definition)]
    cache.cache_segment(audience_id, ids, ttl)
    return ids


def sendable_person_ids(db: Session, person_ids: list[str]) -> set[str]:
    """Set-based sendability: from the given ids, return those that are active,
    consented, not do-not-contact, and NOT suppressed — in one query with a
    NOT EXISTS against suppressions (instead of 2 queries per recipient)."""
    if not person_ids:
        return set()
    P, Sup = models.Person, mx.Suppression
    supp = exists(select(Sup.id).where(func.lower(Sup.email) == func.lower(P.primary_email)))
    rows = (db.query(P.id)
            .filter(P.id.in_(person_ids),
                    P.is_active.is_(True),
                    P.do_not_contact.is_(False),
                    P.primary_email.isnot(None),
                    or_(P.consent_status.is_(None), P.consent_status != "denied"),
                    ~supp)
            .all())
    return {r[0] for r in rows}


def _last_token(name: str | None) -> str:
    return (name or "").strip().lower().split(" ")[-1] if name else ""


def dedupe_candidates(db: Session, tenant_scoped: bool = False) -> list[dict]:
    """Blocking-key duplicate detection. Instead of comparing every pair
    (O(N^2)), only compare within blocks:
      block 1: exact lower(primary_email)
      block 2: (last-name token, current_org_id)
    Emits candidate pairs. Comparisons are O(sum block_size^2), which for real
    data is a tiny fraction of N^2."""
    persons = (db.query(models.Person.id, models.Person.full_name,
                        models.Person.primary_email, models.Person.current_org_id,
                        models.Person.linkedin_url)
               .filter(models.Person.is_active.is_(True)).all())
    email_blocks: dict[str, list] = {}
    nameorg_blocks: dict[tuple, list] = {}
    linkedin_blocks: dict[str, list] = {}
    for pid, name, email, org, li in persons:
        if email:
            email_blocks.setdefault(email.strip().lower(), []).append(pid)
        if li:
            linkedin_blocks.setdefault(li.strip().lower(), []).append(pid)
        lt = _last_token(name)
        if lt and org:
            nameorg_blocks.setdefault((lt, org), []).append(pid)

    seen: set[tuple] = set()
    out: list[dict] = []

    def pairs(block_ids, reason):
        for i in range(len(block_ids)):
            for j in range(i + 1, len(block_ids)):
                key = tuple(sorted([block_ids[i], block_ids[j]]))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"a_id": key[0], "b_id": key[1], "reason": reason})

    for ids in email_blocks.values():
        if len(ids) > 1:
            pairs(ids, "exact_email")
    for ids in linkedin_blocks.values():
        if len(ids) > 1:
            pairs(ids, "exact_linkedin")
    for ids in nameorg_blocks.values():
        if len(ids) > 1:
            pairs(ids, "name+org")
    return out
