"""Signal Review router — FastAPI replacement for the Signal Engine handoff's
Flask blueprint (drip_integration/abm_engine/signal_integration/blueprint.py),
adapted to drip_platform's actual stack.

Scope, unchanged from the original safety model:
  - Reads and writes ONLY signal_engine's own shadow SQLite database
    (SIGNAL_V2_DB, default ./signal_engine.db). It never touches Postgres,
    never touches models.Signal, never touches drafts/sequences/outreach.
  - Promoting a signal_engine observation into DRIP's real `signals` table is
    a SEPARATE, explicit step (abm_platform.services.signal_v2_bridge),
    triggered by a human running the export script -- never automatically
    from this router.
  - The webhook receivers (HubSpot, generic first-party) only ingest into the
    shadow database's `observations`/capture tables -- same boundary.

Registered additively in main.py via app.include_router(signal_review.router).
Reachable from the DRIP OS SPA via the new "Signal Review" nav entry added to
routers/os_shell.py (a fetch() call to the JSON endpoints below, not a
server-rendered template -- keeps everything inside the one interface the
team already uses instead of a second, easy-to-forget page).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/signal-review", tags=["signal-review-v2"])


def _db_path() -> Path:
    # Single source of truth: signal_engine.cli.DEFAULT_DB (work/signal_engine.db).
    # This MUST match what `python -m signal_engine.cli ...` uses by default,
    # since that's what the autonomous scheduled pipeline (run_signal_pipeline.bat)
    # actually writes to. A prior version of this file defaulted to a different,
    # separate root-level `signal_engine.db` path, which silently left this
    # dashboard (and the export bridge) reading a stale, near-empty file while
    # all real captured data accumulated in work/signal_engine.db instead.
    from signal_engine.cli import DEFAULT_DB
    env = os.environ.get("SIGNAL_V2_DB")
    return Path(env) if env else DEFAULT_DB


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


@router.get("")
def review_queue(status: str = "open"):
    """Mirrors the original blueprint's review_page(), JSON instead of a
    server-rendered template -- consumed by the new os_shell.py screen."""
    if not _db_path().exists():
        raise HTTPException(503, "signal_engine.db not found -- run `python -m signal_engine.cli init` first")
    with closing(_connect()) as con:
        reviews = [dict(r) for r in con.execute(
            """SELECT r.id, r.reason_code, r.created_at, o.title, o.body, o.canonical_url, o.published_at
               FROM reviews r JOIN observations o ON o.id = r.observation_id
               WHERE r.status = ? ORDER BY r.created_at DESC LIMIT 100""", (status,),
        )]
        accounts = [dict(r) for r in con.execute(
            "SELECT id, canonical_name FROM accounts WHERE active=1 ORDER BY canonical_name")]
        signals = [dict(r) for r in con.execute(
            """SELECT s.*, a.canonical_name FROM signals s JOIN accounts a ON a.id = s.account_id
               WHERE s.status='active' ORDER BY s.event_at DESC LIMIT 100""")]
        market = [dict(r) for r in con.execute(
            "SELECT title, published_at, canonical_url FROM observations WHERE status='market' ORDER BY published_at DESC LIMIT 100")]
    return {"reviews": reviews, "accounts": accounts, "signals": signals, "market": market}


class ResolveReq(BaseModel):
    resolution: str
    account: str | None = None


@router.post("/{review_id}/resolve")
def resolve_review(review_id: str, req: ResolveReq):
    from signal_engine.pipeline import Pipeline
    try:
        with closing(_connect()) as con:
            result = Pipeline(con).resolve_review(review_id, req.resolution, req.account)
        return {"ok": True, **result}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/status")
def signal_v2_status():
    """Coverage/health/quality snapshot -- the same numbers the CLI's
    daily-report and PRODUCTION_READINESS.md use, so the DRIP OS shows the
    exact same honest gate state as the command line, not a friendlier one.

    Two independent production gates, both required before real migration:
      - 360 coverage (capture_360): needs >=90% fresh account/channel checks.
      - quality calibration (quality): needs >=100 human-reviewed samples at
        >=90% agreement with the automated quality_decision.
    Neither gate is computed here -- both come straight from signal_engine's
    own audit functions, so this can never drift from what `python -m
    signal_engine.cli capture-audit` / `quality-audit` would print."""
    if not _db_path().exists():
        return {"initialized": False}
    from signal_engine.pipeline import Pipeline
    from signal_engine.capture import CaptureService
    with closing(_connect()) as con:
        base = Pipeline(con).status()
        try:
            quality = Pipeline(con).quality_audit()
        except Exception as exc:  # pragma: no cover -- surfaced, not swallowed
            quality = {"error": str(exc)}
        try:
            capture_360 = CaptureService(con).coverage()
            capture_360 = {k: capture_360[k] for k in
                           ("capture_360_ready", "readiness_threshold", "required_coverage_ratio")
                           if k in capture_360}
        except Exception as exc:  # pragma: no cover
            capture_360 = {"error": str(exc)}
    return {"initialized": True, **base, "quality": quality, "capture_360": capture_360}


@router.get("/coverage")
def signal_v2_coverage():
    """Detailed source/channel coverage for the operator command center.

    Read-only: opens the signal-engine SQLite file and asks CaptureService for
    its coverage matrix. Creates nothing, commits nothing, and touches no
    Postgres table -- the same discipline the export preview was fixed to
    follow. 503 rather than an empty result when the engine has never been
    initialized, so the UI can say "not set up" instead of "0% coverage",
    which would read as a real measurement.
    """
    if not _db_path().exists():
        raise HTTPException(503, "signal engine is not initialized")
    from signal_engine.capture import CaptureService
    with closing(_connect()) as con:
        return CaptureService(con).coverage()


@router.post("/capture/{channel_id}")
async def capture_webhook(channel_id: str, request: Request):
    """Passive first-party receiver -- never calls a provider or outreach code.

    Signed with a timestamped HMAC-SHA256 (x-signal-timestamp + x-signal-
    signature headers) instead of a reusable static bearer token: a captured
    request can't be replayed after 5 minutes, and a captured signature can't
    be reused to forge a DIFFERENT payload, since the signature covers the
    body itself. This is our own first-party sender on both ends, so we own
    the signing scheme -- not a third-party webhook we don't control."""
    from signal_engine.capture import CaptureService
    secret = os.environ.get("SIGNAL_CAPTURE_WEBHOOK_SECRET", "")
    timestamp = request.headers.get("x-signal-timestamp", "")
    supplied = request.headers.get("x-signal-signature", "")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "payload too large")
    try:
        fresh = abs(time.time() - int(timestamp)) <= 300
    except ValueError:
        fresh = False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body,
                        hashlib.sha256).hexdigest() if secret else ""
    if not secret or not fresh or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "invalid or stale signature")
    try:
        with closing(_connect()) as con:
            result = CaptureService(con).ingest_json(channel_id, body)
        return {"ok": True, **result}
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/capture/hubspot")
async def hubspot_capture_webhook(request: Request):
    """HubSpot webhook receiver with v1 signature verification -- HubSpot is
    the active CRM signal source per the integration requirements. Object IDs
    are resolved to signal_engine accounts inside CaptureService.ingest_hubspot;
    they are NOT treated as trustworthy DRIP account IDs (see CLAUDE_HANDOFF.md
    'Known integration caution')."""
    from signal_engine.capture import CaptureService
    secret = os.environ.get("HUBSPOT_CLIENT_SECRET", "")
    body = await request.body()
    supplied = request.headers.get("x-hubspot-signature", "")
    expected = hashlib.sha256(secret.encode("utf-8") + body).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "invalid HubSpot signature")
    if len(body) > 1_000_000:
        raise HTTPException(413, "payload too large")
    try:
        with closing(_connect()) as con:
            result = CaptureService(con).ingest_hubspot(body)
        return {"ok": True, **result}
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))
