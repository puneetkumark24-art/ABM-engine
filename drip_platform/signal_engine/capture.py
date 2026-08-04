from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import ipaddress
import socket
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from .pipeline import Pipeline, iso, normalize_text, now_utc, parse_datetime


class _VisibleTextParser(HTMLParser):
    """Extract stable user-visible page text while ignoring scripts and styling."""
    ignored = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() in self.ignored:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag.casefold() in self.ignored and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def stable_page_text(raw: bytes) -> str:
    decoded = raw.decode("utf-8", errors="replace")
    if "<" not in decoded or ">" not in decoded:
        return normalize_text(decoded)
    parser = _VisibleTextParser()
    parser.feed(decoded)
    return normalize_text(" ".join(parser.parts))


CHANNELS = [
    ("public_news", "poll", 240, 1),
    ("regulator", "poll", 360, 1),
    ("exchange", "poll", 180, 1),
    ("official_site", "change", 360, 1),
    ("careers", "change", 720, 1),
    ("procurement", "poll", 360, 1),
    ("linkedin_company", "api_or_import", 360, 1),
    ("linkedin_people", "provider_or_import", 720, 1),
    ("linkedin_jobs", "provider_or_import", 720, 1),
    ("crm", "webhook_or_import", 60, 1),
    ("email_engagement", "signed_webhook_or_import", 15, 1),
    ("website_intent", "webhook_or_import", 15, 1),
    ("app_releases", "poll", 1440, 0),
    ("social_other", "api_or_import", 720, 0),
]

SENSITIVE_KEYS = {"email", "phone", "mobile", "authorization", "access_token", "refresh_token",
                  "api_key", "apikey", "password", "cookie", "secret"}


def sanitize_payload(value, depth: int = 0):
    """Bound and redact raw capture payloads before durable storage."""
    if depth > 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if str(k).casefold() in SENSITIVE_KEYS else sanitize_payload(v, depth + 1)
                for k, v in list(value.items())[:200]}
    if isinstance(value, list):
        return [sanitize_payload(v, depth + 1) for v in value[:200]]
    if isinstance(value, str):
        return value[:10000]
    return value


def validate_public_url(url: str, resolve_dns: bool = False) -> str:
    parts = urlsplit(url)
    if parts.scheme.casefold() != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("watch URL must be a credential-free HTTPS URL")
    host = parts.hostname.casefold().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("local/private watch URLs are forbidden")
    addresses = []
    try:
        addresses.append(ipaddress.ip_address(host))
    except ValueError:
        if resolve_dns:
            addresses.extend(ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    if any(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved for ip in addresses):
        raise ValueError("local/private watch URLs are forbidden")
    return url


CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS capture_channels (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    cadence_minutes INTEGER NOT NULL,
    required INTEGER NOT NULL DEFAULT 1,
    configured INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_event_at TEXT,
    last_error TEXT,
    events_total INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS capture_targets (
    account_id TEXT NOT NULL REFERENCES accounts(id),
    channel_id TEXT NOT NULL REFERENCES capture_channels(id),
    required INTEGER NOT NULL DEFAULT 1,
    cadence_minutes INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(account_id,channel_id)
);
CREATE TABLE IF NOT EXISTS capture_events (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES capture_channels(id),
    external_id TEXT NOT NULL,
    account_id TEXT REFERENCES accounts(id),
    person_name TEXT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    url TEXT,
    event_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'captured',
    UNIQUE(channel_id,external_id)
);
CREATE INDEX IF NOT EXISTS idx_capture_events_account ON capture_events(account_id,event_at);
CREATE INDEX IF NOT EXISTS idx_capture_events_channel ON capture_events(channel_id,event_at);
CREATE TABLE IF NOT EXISTS page_watch_targets (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id),
    channel_id TEXT NOT NULL REFERENCES capture_channels(id),
    url TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_hash TEXT,
    last_checked_at TEXT,
    last_changed_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS page_snapshots (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES page_watch_targets(id),
    content_hash TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    UNIQUE(target_id,content_hash)
);
CREATE TABLE IF NOT EXISTS capture_gap_alerts (
    account_id TEXT NOT NULL REFERENCES accounts(id),
    channel_id TEXT NOT NULL REFERENCES capture_channels(id),
    status TEXT NOT NULL DEFAULT 'open',
    reason TEXT NOT NULL,
    first_detected_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY(account_id,channel_id)
);
"""


def initialize_capture(con: sqlite3.Connection) -> None:
    con.executescript(CAPTURE_SCHEMA)
    for channel_id, mode, cadence, required in CHANNELS:
        con.execute(
            """INSERT INTO capture_channels(id,mode,cadence_minutes,required) VALUES(?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,cadence_minutes=excluded.cadence_minutes,required=excluded.required""",
            (channel_id, mode, cadence, required),
        )
    accounts = con.execute("SELECT id FROM accounts WHERE active=1").fetchall()
    for account in accounts:
        for channel_id, _mode, cadence, required in CHANNELS:
            con.execute(
                """INSERT OR IGNORE INTO capture_targets(account_id,channel_id,required,cadence_minutes)
                   VALUES(?,?,?,?)""", (account["id"], channel_id, required, cadence),
            )
    con.commit()


class CaptureService:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        initialize_capture(con)
        self.pipeline = Pipeline(con)

    def configure_channel(self, channel_id: str, enabled: bool = True) -> None:
        changed = self.con.execute(
            "UPDATE capture_channels SET configured=1,enabled=? WHERE id=?", (int(enabled), channel_id)
        ).rowcount
        if not changed:
            raise ValueError(f"unknown capture channel: {channel_id}")
        self.con.commit()

    def mark_channel_success(self, channel_id: str, at: datetime | None = None, error: str | None = None) -> None:
        at = at or now_utc()
        self.con.execute(
            """UPDATE capture_channels SET configured=1,enabled=1,last_success_at=?,last_error=? WHERE id=?""",
            (iso(at), error, channel_id),
        )
        self.con.commit()

    def _account(self, record: dict) -> str | None:
        explicit = normalize_text(str(record.get("account_id") or ""))
        if explicit and self.con.execute("SELECT 1 FROM accounts WHERE id=?", (explicit,)).fetchone():
            return explicit
        title = str(record.get("title") or record.get("headline") or "")
        detail = str(record.get("detail") or record.get("summary") or record.get("text") or "")
        attribution = self.pipeline.attribute(title, detail, record.get("url"))
        return attribution.account_id if not attribution.ambiguous else None

    def ingest_records(self, channel_id: str, records: Iterable[dict], observed_at: datetime | None = None) -> dict:
        channel = self.con.execute("SELECT * FROM capture_channels WHERE id=?", (channel_id,)).fetchone()
        if channel is None:
            raise ValueError(f"unknown capture channel: {channel_id}")
        observed_at = observed_at or now_utc()
        accepted = duplicates = unattributed = 0
        for record in records:
            title = normalize_text(str(record.get("title") or record.get("headline") or record.get("event") or "Activity event"))
            detail = normalize_text(str(record.get("detail") or record.get("summary") or record.get("text") or ""))
            external_id = str(record.get("external_id") or record.get("id") or hashlib.sha256(
                json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest())
            event_at = parse_datetime(str(record.get("event_at") or record.get("timestamp") or ""), observed_at)
            account_id = self._account(record)
            if self.con.execute("SELECT 1 FROM capture_events WHERE channel_id=? AND external_id=?",
                                (channel_id, external_id)).fetchone():
                duplicates += 1
                continue
            self.con.execute(
                    """INSERT INTO capture_events(id,channel_id,external_id,account_id,person_name,event_type,title,detail,url,
                       event_at,observed_at,raw_payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), channel_id, external_id, account_id, record.get("person_name"),
                     str(record.get("event_type") or record.get("event") or "activity"), title, detail, record.get("url"),
                     iso(event_at), iso(observed_at), json.dumps(sanitize_payload(record), sort_keys=True, ensure_ascii=False)[:100000]),
                )
            accepted += 1
            unattributed += int(account_id is None)
        self.con.execute(
            """UPDATE capture_channels SET configured=1,enabled=1,last_success_at=?,
               last_event_at=CASE WHEN ?>0 THEN ? ELSE last_event_at END,last_error=NULL,
               events_total=events_total+? WHERE id=?""",
            (iso(observed_at), accepted, iso(observed_at), accepted, channel_id),
        )
        self.con.commit()
        return {"channel": channel_id, "accepted": accepted, "duplicates": duplicates, "unattributed": unattributed}

    def ingest_json(self, channel_id: str, payload: str | bytes) -> dict:
        data = json.loads(payload)
        records = data if isinstance(data, list) else data.get("events", [data])
        return self.ingest_records(channel_id, records)

    def ingest_jsonl(self, channel_id: str, payload: str) -> dict:
        records = [json.loads(line) for line in payload.splitlines() if line.strip()]
        return self.ingest_records(channel_id, records)

    def ingest_linkedin_csv(self, payload: str, channel_id: str = "linkedin_company") -> dict:
        if channel_id not in {"linkedin_company", "linkedin_people", "linkedin_jobs"}:
            raise ValueError("LinkedIn import channel must be linkedin_company, linkedin_people, or linkedin_jobs")
        reader = csv.DictReader(io.StringIO(payload))
        records = []
        for row in reader:
            records.append({
                "external_id": row.get("external_id") or row.get("post_id") or row.get("profile_url"),
                "account_id": row.get("account_id"), "person_name": row.get("person_name") or row.get("name"),
                "event_type": row.get("event_type") or "linkedin_activity",
                "title": row.get("title") or row.get("post_text") or row.get("headline") or "LinkedIn activity",
                "detail": row.get("detail") or row.get("post_text") or "",
                "url": row.get("url") or row.get("post_url") or row.get("profile_url"),
                "event_at": row.get("event_at") or row.get("published_at"),
            })
        return self.ingest_records(channel_id, records)

    def ingest_hubspot(self, payload: str | bytes) -> dict:
        """Normalize HubSpot webhook events or enriched CRM exports."""
        data = json.loads(payload)
        items = data if isinstance(data, list) else data.get("events", data.get("results", [data]))
        records = []
        for item in items:
            props = item.get("properties") or {}
            subscription = str(item.get("subscriptionType") or item.get("eventType") or "crm.activity")
            object_id = item.get("objectId") or item.get("id") or props.get("hs_object_id")
            property_name, property_value = item.get("propertyName"), item.get("propertyValue")
            if property_name and property_value is not None:
                props = {**props, property_name: property_value}
            account_name = props.get("company") or props.get("name") or item.get("companyName") or ""
            detail = "; ".join(f"{k}={v}" for k, v in sorted(props.items()) if v not in (None, ""))
            occurred = item.get("occurredAt") or item.get("timestamp") or item.get("event_at")
            if isinstance(occurred, (int, float)):
                occurred = datetime.fromtimestamp(occurred / 1000, timezone.utc).isoformat()
            records.append({
                "external_id": f"hubspot:{item.get('eventId') or object_id}:{subscription}:{property_name or ''}:{occurred or ''}",
                "account_id": item.get("account_id"),
                "event_type": f"hubspot_{subscription.replace('.', '_')}",
                "title": item.get("title") or f"HubSpot {subscription}: {account_name or object_id}",
                "detail": detail or str(item.get("changeSource") or "HubSpot CRM activity"),
                "url": item.get("url"), "event_at": occurred,
            })
        return self.ingest_records("crm", records)

    def add_watch(self, target_id: str, channel_id: str, url: str, label: str, account_id: str | None = None) -> None:
        url = validate_public_url(url)
        self.con.execute(
            """INSERT INTO page_watch_targets(id,account_id,channel_id,url,label) VALUES(?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET account_id=excluded.account_id,channel_id=excluded.channel_id,
               url=excluded.url,label=excluded.label,enabled=1""", (target_id, account_id, channel_id, url, label),
        )
        self.configure_channel(channel_id)
        self.con.commit()

    def ingest_watch_csv(self, payload: str) -> dict:
        """Bulk-configure official, careers, procurement, release, or other page watches."""
        accepted = rejected = 0
        errors = []
        for line, row in enumerate(csv.DictReader(io.StringIO(payload)), start=2):
            try:
                target_id = normalize_text(row.get("id") or "")
                channel_id = normalize_text(row.get("channel") or row.get("channel_id") or "")
                url = normalize_text(row.get("url") or "")
                label = normalize_text(row.get("label") or target_id)
                account_id = normalize_text(row.get("account_id") or "") or None
                if not target_id or not channel_id or not url:
                    raise ValueError("id, channel, and url are required")
                validate_public_url(url)
                if not self.con.execute("SELECT 1 FROM capture_channels WHERE id=?", (channel_id,)).fetchone():
                    raise ValueError(f"unknown channel: {channel_id}")
                if account_id and not self.con.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
                    raise ValueError(f"unknown account: {account_id}")
                self.add_watch(target_id, channel_id, url, label, account_id)
                accepted += 1
            except Exception as exc:
                rejected += 1
                errors.append({"line": line, "error": str(exc)})
        return {"accepted": accepted, "rejected": rejected, "errors": errors}

    def seed_official_watches(self) -> dict:
        created = 0
        for account in self.con.execute("SELECT id,canonical_name,domains_json FROM accounts WHERE active=1").fetchall():
            domains = json.loads(account["domains_json"])
            if not domains:
                continue
            self.add_watch(f"official-{account['id']}", "official_site", f"https://{domains[0]}",
                           f"{account['canonical_name']} official site", account["id"])
            created += 1
        return {"official_watches": created}

    def record_page(self, target_id: str, raw: bytes, observed_at: datetime | None = None) -> dict:
        observed_at = observed_at or now_utc()
        target = self.con.execute("SELECT * FROM page_watch_targets WHERE id=? AND enabled=1", (target_id,)).fetchone()
        if target is None:
            raise ValueError("unknown or disabled watch target")
        text = stable_page_text(raw)
        if not text:
            raise ValueError("page produced no stable visible text")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        changed = target["last_hash"] is not None and target["last_hash"] != content_hash
        first_capture = target["last_hash"] is None
        self.con.execute(
            "INSERT OR IGNORE INTO page_snapshots(id,target_id,content_hash,captured_at,normalized_text) VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), target_id, content_hash, iso(observed_at), text),
        )
        self.con.execute(
            """UPDATE page_watch_targets SET last_hash=?,last_checked_at=?,last_changed_at=CASE WHEN ? THEN ? ELSE last_changed_at END,
               last_error=NULL WHERE id=?""", (content_hash, iso(observed_at), int(changed), iso(observed_at), target_id),
        )
        if changed:
            self.ingest_records(target["channel_id"], [{
                "external_id": f"{target_id}:{content_hash}", "account_id": target["account_id"],
                "event_type": "page_changed", "title": f"{target['label']} changed", "detail": text[:2000],
                "url": target["url"], "event_at": iso(observed_at),
            }], observed_at)
        self.con.commit()
        return {"target": target_id, "first_capture": first_capture, "changed": changed, "content_hash": content_hash}

    def coverage(self, at: datetime | None = None) -> dict:
        at = at or now_utc()
        channels = [dict(r) for r in self.con.execute("SELECT * FROM capture_channels ORDER BY id")]
        matrix = []
        covered_required = required_total = 0
        for row in self.con.execute(
            """SELECT t.account_id,a.canonical_name,t.channel_id,t.required,t.cadence_minutes,t.enabled,
               c.configured,c.enabled channel_enabled,c.last_success_at,c.last_event_at,c.last_error
               FROM capture_targets t JOIN accounts a ON a.id=t.account_id JOIN capture_channels c ON c.id=t.channel_id
               WHERE a.active=1 ORDER BY a.canonical_name,t.channel_id"""
        ):
            global_channels = {"public_news", "regulator", "exchange"}
            if row["channel_id"] in global_channels:
                last = row["last_success_at"]
            else:
                event_last = self.con.execute(
                    "SELECT MAX(event_at) FROM capture_events WHERE account_id=? AND channel_id=?",
                    (row["account_id"], row["channel_id"]),
                ).fetchone()[0]
                watch_last = self.con.execute(
                    "SELECT MAX(last_checked_at) FROM page_watch_targets WHERE account_id=? AND channel_id=? AND enabled=1",
                    (row["account_id"], row["channel_id"]),
                ).fetchone()[0]
                last = max((value for value in (event_last, watch_last) if value), default=None)
            fresh = bool(last and at - datetime.fromisoformat(last) <= timedelta(minutes=row["cadence_minutes"] * 2))
            covered = bool(row["enabled"] and row["configured"] and row["channel_enabled"] and fresh and not row["last_error"])
            required_total += int(row["required"])
            covered_required += int(row["required"] and covered)
            matrix.append({"account_id": row["account_id"], "account": row["canonical_name"], "channel": row["channel_id"],
                           "required": bool(row["required"]), "covered": covered, "last_success_at": last,
                           "gap": None if covered else "not_configured" if not row["configured"] else "disabled" if not row["channel_enabled"] else "stale_or_never_run"})
        ratio = covered_required / required_total if required_total else 0.0
        by_channel = []
        for channel_id, *_ in CHANNELS:
            required_rows = [x for x in matrix if x["channel"] == channel_id and x["required"]]
            covered_rows = [x for x in required_rows if x["covered"]]
            by_channel.append({"channel": channel_id, "covered_accounts": len(covered_rows),
                               "required_accounts": len(required_rows),
                               "coverage_ratio": len(covered_rows) / len(required_rows) if required_rows else 1.0})
        return {"capture_360_ready": ratio >= .90, "readiness_threshold": .90, "required_coverage_ratio": ratio,
                "required_covered": covered_required, "required_total": required_total,
                "by_channel": by_channel, "channels": channels, "matrix": matrix}

    def refresh_gap_alerts(self, at: datetime | None = None) -> dict:
        at = at or now_utc()
        report = self.coverage(at)
        open_keys = set()
        for item in report["matrix"]:
            if item["required"] and not item["covered"]:
                key = (item["account_id"], item["channel"]); open_keys.add(key)
                self.con.execute(
                    """INSERT INTO capture_gap_alerts(account_id,channel_id,reason,first_detected_at,last_seen_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(account_id,channel_id) DO UPDATE SET status='open',reason=excluded.reason,
                       last_seen_at=excluded.last_seen_at,resolved_at=NULL""",
                    (*key, item["gap"], iso(at), iso(at)),
                )
        for row in self.con.execute("SELECT account_id,channel_id FROM capture_gap_alerts WHERE status='open'").fetchall():
            key = (row["account_id"], row["channel_id"])
            if key not in open_keys:
                self.con.execute("UPDATE capture_gap_alerts SET status='resolved',resolved_at=? WHERE account_id=? AND channel_id=?",
                                 (iso(at), *key))
        self.con.commit()
        return {"capture_360_ready": report["capture_360_ready"], "readiness_threshold": report["readiness_threshold"],
                "required_coverage_ratio": report["required_coverage_ratio"], "open_gaps": len(open_keys),
                "required_total": report["required_total"], "by_channel": report["by_channel"]}


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")
