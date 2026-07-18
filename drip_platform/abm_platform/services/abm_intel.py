"""
abm_intel.py — Sprint 4: ABM Intelligence.

Three capabilities the audit flagged as weak/manual:
  1. Buying-committee inference — map a person's title/seniority/function to a
     canonical committee role, then materialize/score the committee for an org
     and report coverage gaps (6sense/Demandbase-style).
  2. Signal ingestion with content-hash dedup — the same news/tender seen twice
     is stored once (idempotent collectors).
  3. Account scoring — combine signal recency/volume with committee coverage
     into an AccountScore row.

Writes only to existing tables (buying_committee_members, signals,
account_scores); the sole schema change is an additive signals.content_hash.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models

# Canonical B2B buying-committee roles (Gartner/CEB model, trimmed).
CANONICAL_ROLES = ["economic_buyer", "executive_sponsor", "champion",
                   "technical_buyer", "user"]

# Ordered rules: first match wins. Checked against lowercased title+function.
_ROLE_RULES = [
    ("economic_buyer", ("cfo", "chief financial", "head of finance", "procurement",
                        "budget", "treasurer")),
    ("executive_sponsor", ("ceo", "chief executive", "managing director", "president",
                           "board", "chairman", "cxo")),
    ("technical_buyer", ("cto", "chief technology", "cio", "chief information",
                         "architect", "head of it", "security", "infrastructure",
                         "engineering")),
    ("champion", ("head of", "director", "vp", "vice president", "lead", "manager",
                  "transformation", "digital", "innovation")),
    ("user", ("analyst", "officer", "specialist", "associate", "executive",
              "operations", "relationship")),
]


def infer_role(title: str | None, seniority: str | None = None,
               function: str | None = None) -> str:
    hay = " ".join(x for x in (title, function) if x).lower()
    for role, kws in _ROLE_RULES:
        if any(k in hay for k in kws):
            return role
    # seniority fallback
    s = (seniority or "").lower()
    if s in ("c-level", "cxo", "executive"):
        return "executive_sponsor"
    if s in ("vp", "director", "head"):
        return "champion"
    return "user"


def _warmth(p) -> float:
    try:
        return float(getattr(p, "warmness", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _engagement_for(p: models.Person) -> str:
    if getattr(p, "replied", False) or _warmth(p) >= 3:
        return "engaged"
    if getattr(p, "outreach_messaged", False):
        return "contacted"
    return "identified"


def infer_committee(db: Session, org_id: str, product_id: str | None = None) -> dict:
    """Upsert a BuyingCommitteeMember for every active person in the org, with an
    inferred role + engagement. Idempotent per (org, person, product)."""
    people = (db.query(models.Person)
              .filter(models.Person.current_org_id == org_id,
                      models.Person.is_active == True).all())  # noqa: E712
    created = updated = 0
    for p in people:
        role = infer_role(p.current_title, p.seniority_level, p.function)
        eng = _engagement_for(p)
        m = (db.query(models.BuyingCommitteeMember)
             .filter_by(org_id=org_id, person_id=p.id, product_id=product_id).first())
        if m is None:
            db.add(models.BuyingCommitteeMember(org_id=org_id, person_id=p.id,
                                                product_id=product_id,
                                                committee_role=role, engagement=eng))
            created += 1
        else:
            m.committee_role = role; m.engagement = eng
            updated += 1
    db.commit()
    return {"org_id": org_id, "people": len(people), "created": created,
            "updated": updated}


def committee_coverage(db: Session, org_id: str, product_id: str | None = None) -> dict:
    members = (db.query(models.BuyingCommitteeMember)
               .filter_by(org_id=org_id, product_id=product_id).all())
    covered = {m.committee_role for m in members}
    missing = [r for r in CANONICAL_ROLES if r not in covered]
    engaged = sum(1 for m in members if m.engagement == "engaged")
    return {"org_id": org_id, "members": len(members),
            "roles_covered": sorted(covered & set(CANONICAL_ROLES)),
            "roles_missing": missing,
            "coverage_pct": round(100 * (len(CANONICAL_ROLES) - len(missing)) / len(CANONICAL_ROLES), 1),
            "engaged_members": engaged,
            "single_threaded": len(members) < 2}


# ── signal ingestion with content-hash dedup ─────────────────
def _hash(*parts) -> str:
    return hashlib.sha256("|".join((p or "").strip().lower() for p in parts).encode()).hexdigest()


def ingest_signal(db: Session, org_id: str, signal_type: str, source: str,
                  title: str, summary: str = "", url: str | None = None,
                  urgency: str = "medium") -> tuple[models.Signal, bool]:
    """Insert a signal unless an identical one (same content hash) already exists.
    Returns (signal, created)."""
    h = _hash(org_id, signal_type, title, url or summary)
    existing = db.query(models.Signal).filter_by(content_hash=h).first()
    if existing:
        return existing, False
    # signals.url is UNIQUE in the base schema: the same article ingested by a
    # second collector (different type/source => different hash) must dedup on
    # URL too, not crash.
    if url:
        by_url = db.query(models.Signal).filter_by(url=url).first()
        if by_url:
            return by_url, False
    s = models.Signal(org_id=org_id, signal_type=signal_type, source=source,
                       title=title, summary=summary, url=url, urgency=urgency,
                       content_hash=h)
    db.add(s)
    try:
        db.commit()
    except Exception:  # IntegrityError race — recover, return the winner
        db.rollback()
        winner = (db.query(models.Signal).filter_by(content_hash=h).first()
                  or (db.query(models.Signal).filter_by(url=url).first() if url else None))
        if winner:
            return winner, False
        raise
    return s, True


def score_account(db: Session, org_id: str, now: datetime | None = None) -> models.AccountScore:
    """Blend recent-signal volume with committee coverage into an AccountScore."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=90)
    recent = (db.query(models.Signal)
              .filter(models.Signal.org_id == org_id,
                      models.Signal.created_at >= since).count())
    signal_score = min(100, recent * 15)
    cov = committee_coverage(db, org_id)
    relationship_score = int(cov["coverage_pct"])
    total = round(0.6 * signal_score + 0.4 * relationship_score, 1)
    tier = "A" if total >= 70 else "B" if total >= 40 else "C"
    row = models.AccountScore(org_id=org_id, score_date=now, signal_score=signal_score,
                              regulatory_score=0, reachability_score=0,
                              relationship_score=relationship_score,
                              total_score=total, tier=tier,
                              notes=f"{recent} signals/90d; committee {cov['coverage_pct']}%")
    db.add(row); db.commit()
    return row
