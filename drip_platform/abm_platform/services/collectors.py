"""
collectors.py — Parity Mission: the signal-acquisition layer every audit found
missing. The refinery finally gets wells.

Design (Constitution: EXTEND — everything downstream already existed):
  fetch (this module) → parse RSS/Atom (stdlib xml) → map to org (name match)
  → abm_intel.ingest_signal (content-hash DEDUP, existing) → decay/classify
  (existing etl) → scoring/decisions (existing).

Reliability: per-source interval scheduling, consecutive-error counting with
auto-disable at 5, per-run status recording. The fetcher is injectable so
tests run offline and deterministic; the default fetcher uses stdlib urllib
(no credentials, public feeds only — legally clean sources).

Seeded KSA sources cover Saudi banking/business press + SAMA/Tadawul feeds;
sources are data (rows), so adding one is an API call, not a deploy.
"""
from __future__ import annotations
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models
import models_collectors as mc
from abm_platform.services import abm_intel

MAX_CONSECUTIVE_ERRORS = 5

# Public, credential-free KSA business/regulatory feeds (editable rows).
DEFAULT_SOURCES = [
    {"name": "Argaam (EN)", "kind": "rss", "url": "https://www.argaam.com/en/rss",
     "signal_type": "news", "interval_minutes": 60},
    {"name": "Saudi Gazette Business", "kind": "rss",
     "url": "https://saudigazette.com.sa/rssFeed/74", "signal_type": "news",
     "interval_minutes": 120},
    {"name": "Arab News Economy", "kind": "rss",
     "url": "https://www.arabnews.com/cat/3/rss.xml", "signal_type": "news",
     "interval_minutes": 120},
    {"name": "SAMA News (EN)", "kind": "rss",
     "url": "https://www.sama.gov.sa/en-US/News/Pages/rss.aspx",
     "signal_type": "regulatory", "interval_minutes": 240},
]


def seed_default_sources(db: Session) -> int:
    added = 0
    for s in DEFAULT_SOURCES:
        if not db.query(mc.SignalSource).filter_by(url=s["url"]).first():
            db.add(mc.SignalSource(**s)); added += 1
    db.commit()
    return added


def add_source(db: Session, name: str, url: str, kind: str = "rss",
               signal_type: str = "news", interval_minutes: int = 60) -> mc.SignalSource:
    src = mc.SignalSource(name=name, url=url, kind=kind, signal_type=signal_type,
                          interval_minutes=interval_minutes)
    db.add(src); db.commit()
    return src


def _default_fetcher(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "DRIP-SignalCollector/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feed(raw: bytes) -> list[dict]:
    """Parse RSS 2.0 or Atom into [{title, link, summary, published}]."""
    root = ET.fromstring(raw)
    items = []
    # RSS 2.0
    for item in root.iter("item"):
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "summary": (item.findtext("description") or "").strip()[:2000],
            "published": (item.findtext("pubDate") or "").strip()})
    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        link_el = entry.find(f"{ns}link")
        items.append({
            "title": (entry.findtext(f"{ns}title") or "").strip(),
            "link": (link_el.get("href") if link_el is not None else "").strip(),
            "summary": (entry.findtext(f"{ns}summary") or "").strip()[:2000],
            "published": (entry.findtext(f"{ns}updated") or "").strip()})
    return [i for i in items if i["title"]]


def _org_index(db: Session) -> list[tuple[str, str]]:
    """[(lowered name, org_id)] for keyword matching, longest names first so
    'Saudi National Bank' wins over 'Saudi'."""
    rows = db.query(models.Organization.id, models.Organization.canonical_name).all()
    idx = [(name.lower(), oid) for oid, name in rows if name and len(name) >= 4]
    return sorted(idx, key=lambda t: -len(t[0]))


def match_org(title: str, summary: str, idx: list[tuple[str, str]]) -> str | None:
    hay = f"{title} {summary}".lower()
    for name, oid in idx:
        if name in hay:
            return oid
    return None


def run_source(db: Session, source: mc.SignalSource, fetcher=None,
               now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    fetcher = fetcher or _default_fetcher
    created = deduped = matched = 0
    try:
        raw = fetcher(source.url)
        items = parse_feed(raw)
        idx = _org_index(db)
        for it in items[:100]:
            org_id = match_org(it["title"], it["summary"], idx)
            if org_id:
                matched += 1
            sig, was_created = abm_intel.ingest_signal(
                db, org_id=org_id, signal_type=source.signal_type,
                source=source.name, title=it["title"], summary=it["summary"],
                url=it["link"] or None)
            created += 1 if was_created else 0
            deduped += 0 if was_created else 1
        source.last_status = f"ok: {len(items)} items, {created} new, {deduped} dup, {matched} matched"
        source.error_count = 0
        source.items_ingested = (source.items_ingested or 0) + created
    except Exception as e:  # noqa: BLE001
        source.error_count = (source.error_count or 0) + 1
        source.last_status = f"error: {type(e).__name__}: {str(e)[:150]}"
        if source.error_count >= MAX_CONSECUTIVE_ERRORS:
            source.enabled = False
            source.last_status += " — AUTO-DISABLED"
    source.last_run_at = now
    db.commit()
    return {"source": source.name, "status": source.last_status,
            "created": created, "deduped": deduped, "org_matched": matched,
            "enabled": source.enabled}


def run_due(db: Session, fetcher=None, now: datetime | None = None) -> dict:
    """Scheduler entrypoint (cron/worker/console button): run every enabled
    source whose interval has elapsed."""
    now = now or datetime.utcnow()
    results = []
    for src in db.query(mc.SignalSource).filter_by(enabled=True).all():
        due = (src.last_run_at is None or
               src.last_run_at <= now - timedelta(minutes=src.interval_minutes or 60))
        if due:
            results.append(run_source(db, src, fetcher=fetcher, now=now))
    return {"ran": len(results), "results": results}


def sources_health(db: Session) -> list[dict]:
    return [{"id": s.id, "name": s.name, "url": s.url, "type": s.signal_type,
             "enabled": s.enabled, "errors": s.error_count,
             "items_ingested": s.items_ingested, "last_run": str(s.last_run_at or ""),
             "last_status": s.last_status}
            for s in db.query(mc.SignalSource).all()]
