from __future__ import annotations

import os
import sqlite3
import hmac
import hashlib
import json
from contextlib import closing
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for


signal_bp = Blueprint("signal_v2", __name__, template_folder="templates")


def _db_path() -> Path:
    configured = current_app.config.get("SIGNAL_V2_DB") or os.environ.get("SIGNAL_V2_DB", "signal_engine.db")
    return Path(configured)


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@signal_bp.get("/signal-review")
@_login_required
def review_page():
    with closing(_connect()) as con:
        status = request.args.get("status", "open")
        reviews = [dict(r) for r in con.execute(
            """SELECT r.id,r.reason_code,r.created_at,o.title,o.body,o.canonical_url,o.published_at
               FROM reviews r JOIN observations o ON o.id=r.observation_id
               WHERE r.status=? ORDER BY r.created_at DESC LIMIT 100""", (status,),
        )]
        accounts = [dict(r) for r in con.execute("SELECT id,canonical_name FROM accounts WHERE active=1 ORDER BY canonical_name")]
        signals = [dict(r) for r in con.execute(
            """SELECT s.*,a.canonical_name FROM signals s JOIN accounts a ON a.id=s.account_id
               WHERE s.status='active' ORDER BY s.event_at DESC LIMIT 100"""
        )]
        market = [dict(r) for r in con.execute(
            "SELECT title,published_at,canonical_url FROM observations WHERE status='market' ORDER BY published_at DESC LIMIT 100"
        )]
    return render_template("signal_review.html", reviews=reviews, accounts=accounts, signals=signals, market=market)


@signal_bp.post("/api/signal-review/<review_id>/resolve")
@_login_required
def resolve(review_id):
    # Import here so installing the blueprint never starts collectors or jobs.
    from signal_engine.pipeline import Pipeline
    payload = request.get_json(silent=True) or {}
    try:
        with closing(_connect()) as con:
            result = Pipeline(con).resolve_review(review_id, payload.get("resolution", ""), payload.get("account"))
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@signal_bp.get("/api/signal-v2/status")
@_login_required
def status():
    from signal_engine.pipeline import Pipeline
    with closing(_connect()) as con:
        return jsonify(Pipeline(con).status())


@signal_bp.post("/api/signal-capture/<channel_id>")
def capture_webhook(channel_id):
    """Passive first-party receiver. It never calls a provider or outreach code."""
    from signal_engine.capture import CaptureService
    secret = os.environ.get("SIGNAL_CAPTURE_WEBHOOK_SECRET", "")
    supplied = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(supplied, f"Bearer {secret}"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if request.content_length and request.content_length > 1_000_000:
        return jsonify({"ok": False, "error": "payload too large"}), 413
    payload = request.get_data(cache=False)
    try:
        with closing(_connect()) as con:
            result = CaptureService(con).ingest_json(channel_id, payload)
        return jsonify({"ok": True, **result})
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@signal_bp.post("/api/signal-capture/hubspot")
def hubspot_capture_webhook():
    """Receive HubSpot CRM webhooks with v1 signature verification."""
    from signal_engine.capture import CaptureService
    secret = os.environ.get("HUBSPOT_CLIENT_SECRET", "")
    payload = request.get_data(cache=False)
    supplied = request.headers.get("X-HubSpot-Signature", "")
    expected = hashlib.sha256(secret.encode("utf-8") + payload).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(supplied, expected):
        return jsonify({"ok": False, "error": "invalid HubSpot signature"}), 401
    if len(payload) > 1_000_000:
        return jsonify({"ok": False, "error": "payload too large"}), 413
    try:
        with closing(_connect()) as con:
            result = CaptureService(con).ingest_hubspot(payload)
        return jsonify({"ok": True, **result})
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def register_signal_blueprint(app, signal_db: str | Path | None = None) -> None:
    if signal_db is not None:
        app.config["SIGNAL_V2_DB"] = str(signal_db)
    app.register_blueprint(signal_bp)
