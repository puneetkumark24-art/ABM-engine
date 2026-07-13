"""
abm_engine/dashboard/app.py
────────────────────────────
Flask web dashboard for the ABM Intelligence Platform.
Open in browser: http://localhost:5000

Pages:
  /              — Overview: stats, contact breakdown, recent activity
  /drafts        — Review + approve/reject/edit messages before send
  /contacts      — Full contact directory (all relationship types)
  /contact/<id>  — Individual contact detail + touch history
  /intelligence  — News/signal feed
  /api/...       — JSON endpoints for AJAX actions
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv
import sqlite3

# ── path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "abm_engine.db"
ENV_PATH = ROOT / "abm_engine" / ".env"
load_dotenv(ENV_PATH)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "decimal-abm-dev-key-change-me")
CORS(app)


# ── DB helpers ──────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def query(sql, params=(), one=False):
    conn = get_db()
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows[0] if one and rows else rows if not one else None


def execute(sql, params=()):
    conn = get_db()
    conn.execute(sql, params)
    conn.commit()
    conn.close()


# ── ensure drafts table exists ──────────────────────────────────────────────
def ensure_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id  INTEGER,
            channel     TEXT DEFAULT 'email',
            subject     TEXT,
            body        TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT (datetime('now')),
            reviewed_at TEXT,
            sent_at     TEXT,
            reviewer_notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT,
            title       TEXT,
            summary     TEXT,
            url         TEXT,
            relevance   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            is_read     INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS touch_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id  INTEGER,
            channel     TEXT,
            subject     TEXT,
            body        TEXT,
            status      TEXT,
            sent_at     TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


# ── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/")
def overview():
    contacts = query("SELECT * FROM contacts WHERE is_active = 1")
    total = len(contacts)
    by_tier = {}
    by_type = {}
    for c in contacts:
        t = c.get("tier", "COLD")
        by_tier[t] = by_tier.get(t, 0) + 1
        rt = c.get("relationship_type", "target")
        by_type[rt] = by_type.get(rt, 0) + 1

    pending_drafts = query("SELECT COUNT(*) as cnt FROM drafts WHERE status='pending'", one=True)
    pending_count = pending_drafts["cnt"] if pending_drafts else 0

    recent_signals = query("SELECT * FROM signals ORDER BY created_at DESC LIMIT 5")

    return render_template("overview.html",
        total=total, by_tier=by_tier, by_type=by_type,
        pending_count=pending_count, recent_signals=recent_signals,
        contacts=contacts)


@app.route("/drafts")
def drafts():
    status_filter = request.args.get("status", "pending")
    if status_filter == "all":
        rows = query("""
            SELECT d.*, c.name as contact_name, c.company, c.title
            FROM drafts d LEFT JOIN contacts c ON d.contact_id = c.id
            ORDER BY d.created_at DESC
        """)
    else:
        rows = query("""
            SELECT d.*, c.name as contact_name, c.company, c.title
            FROM drafts d LEFT JOIN contacts c ON d.contact_id = c.id
            WHERE d.status = ?
            ORDER BY d.created_at DESC
        """, (status_filter,))
    return render_template("drafts.html", drafts=rows, current_filter=status_filter)


@app.route("/contacts")
def contacts():
    search = request.args.get("q", "")
    tier_filter = request.args.get("tier", "")
    type_filter = request.args.get("type", "")

    sql = "SELECT * FROM contacts WHERE is_active = 1"
    params = []

    if search:
        sql += " AND (name LIKE ? OR company LIKE ? OR title LIKE ?)"
        params += [f"%{search}%"] * 3
    if tier_filter:
        sql += " AND tier = ?"
        params.append(tier_filter)
    if type_filter:
        sql += " AND relationship_type = ?"
        params.append(type_filter)

    sql += " ORDER BY priority_score DESC"
    rows = query(sql, params)

    # get unique values for filters
    all_tiers = sorted(set(c.get("tier","") for c in query("SELECT DISTINCT tier FROM contacts")))
    all_types = sorted(set(c.get("relationship_type","") for c in query("SELECT DISTINCT relationship_type FROM contacts")))

    return render_template("contacts.html", contacts=rows,
        search=search, tier_filter=tier_filter, type_filter=type_filter,
        all_tiers=all_tiers, all_types=all_types)


@app.route("/contact/<int:cid>")
def contact_detail(cid):
    c = query("SELECT * FROM contacts WHERE id = ?", (cid,), one=True)
    if not c:
        return "Contact not found", 404
    touches = query("SELECT * FROM touch_log WHERE contact_id = ? ORDER BY sent_at DESC", (cid,))
    pending = query("SELECT * FROM drafts WHERE contact_id = ? AND status = 'pending'", (cid,))
    return render_template("contact_detail.html", contact=c, touches=touches, pending=pending)


@app.route("/intelligence")
def intelligence():
    signals = query("SELECT * FROM signals ORDER BY created_at DESC LIMIT 50")
    return render_template("intelligence.html", signals=signals)


# ── API endpoints ───────────────────────────────────────────────────────────

@app.route("/api/draft/<int:did>/approve", methods=["POST"])
def api_approve(did):
    execute("UPDATE drafts SET status='approved', reviewed_at=datetime('now') WHERE id=?", (did,))
    return jsonify({"ok": True, "status": "approved"})


@app.route("/api/draft/<int:did>/reject", methods=["POST"])
def api_reject(did):
    notes = request.json.get("notes", "") if request.is_json else ""
    execute("UPDATE drafts SET status='rejected', reviewed_at=datetime('now'), reviewer_notes=? WHERE id=?",
            (notes, did))
    return jsonify({"ok": True, "status": "rejected"})


@app.route("/api/draft/<int:did>/edit", methods=["POST"])
def api_edit(did):
    data = request.json
    body = data.get("body", "")
    subject = data.get("subject", "")
    if body:
        execute("UPDATE drafts SET body=? WHERE id=?", (body, did))
    if subject:
        execute("UPDATE drafts SET subject=? WHERE id=?", (subject, did))
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/send", methods=["POST"])
def api_send(did):
    draft = query("SELECT * FROM drafts WHERE id=?", (did,), one=True)
    if not draft:
        return jsonify({"ok": False, "error": "Draft not found"}), 404
    if draft["status"] != "approved":
        return jsonify({"ok": False, "error": "Draft must be approved first"}), 400

    # Mark as sent (actual sending via channels module happens separately)
    execute("UPDATE drafts SET status='sent', sent_at=datetime('now') WHERE id=?", (did,))
    execute("""INSERT INTO touch_log (contact_id, channel, subject, body, status)
               VALUES (?, ?, ?, ?, 'sent')""",
            (draft["contact_id"], draft["channel"], draft["subject"], draft["body"]))
    # Increment touch count on contact
    execute("UPDATE contacts SET current_touch = current_touch + 1 WHERE id=?", (draft["contact_id"],))
    return jsonify({"ok": True, "status": "sent"})


@app.route("/api/signal/<int:sid>/read", methods=["POST"])
def api_mark_read(sid):
    execute("UPDATE signals SET is_read=1 WHERE id=?", (sid,))
    return jsonify({"ok": True})


@app.route("/api/contacts/stats")
def api_stats():
    total = query("SELECT COUNT(*) as cnt FROM contacts WHERE is_active=1", one=True)["cnt"]
    hot = query("SELECT COUNT(*) as cnt FROM contacts WHERE tier='HOT' AND is_active=1", one=True)["cnt"]
    warm = query("SELECT COUNT(*) as cnt FROM contacts WHERE tier='WARM' AND is_active=1", one=True)["cnt"]
    cold = query("SELECT COUNT(*) as cnt FROM contacts WHERE tier='COLD' AND is_active=1", one=True)["cnt"]
    pending = query("SELECT COUNT(*) as cnt FROM drafts WHERE status='pending'", one=True)["cnt"]
    sent = query("SELECT COUNT(*) as cnt FROM drafts WHERE status='sent'", one=True)["cnt"]
    return jsonify({"total": total, "hot": hot, "warm": warm, "cold": cold,
                    "pending_drafts": pending, "sent_messages": sent})


# ── Start server ────────────────────────────────────────────────────────────
def run_dashboard(host="0.0.0.0", port=5000, debug=True):
    ensure_tables()
    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║  ABM Intelligence Dashboard                  ║")
    print(f"  ║  Open: http://localhost:{port}                ║")
    print(f"  ║  Press Ctrl+C to stop                        ║")
    print(f"  ╚══════════════════════════════════════════════╝\n")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_dashboard()
