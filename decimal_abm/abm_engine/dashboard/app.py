"""
app.py — ABM Dashboard (SQLite, Claude-based system)
Human review UI for draft_messages / accounts / contacts, backed by
abm_engine/database/db.py — the same store the orchestrator/scoring engine use.
"""
from __future__ import annotations
import os, sys, hmac, hashlib, time as _time
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g
from flask_cors import CORS
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / "abm_engine" / ".env"
load_dotenv(ENV_PATH)

sys.path.insert(0, str(ROOT))
from abm_engine.database import db

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "decimal-abm-CHANGE-ME-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "decimal2026")
UNSUBSCRIBE_BASE = os.environ.get("UNSUBSCRIBE_URL", "http://localhost:5000/unsubscribe")
LOGIN_ATTEMPTS = {}; MAX_ATTEMPTS = 5; LOCKOUT_SECONDS = 300

db.init_db()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"): return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr
    if request.method == "POST":
        now = _time.time()
        attempts = LOGIN_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < LOCKOUT_SECONDS]
        if len(attempts) >= MAX_ATTEMPTS:
            return render_template("login.html", error=f"Too many attempts. Try again in {int(LOCKOUT_SECONDS/60)} minutes.")
        pwd = request.form.get("password", "")
        if hmac.compare_digest(pwd.encode(), DASHBOARD_PASSWORD.encode()):
            session["authenticated"] = True; LOGIN_ATTEMPTS.pop(ip, None)
            db.log_action("LOGIN", f"Successful from {ip}"); return redirect("/")
        else:
            attempts.append(now); LOGIN_ATTEMPTS[ip] = attempts
            db.log_action("LOGIN_FAIL", f"Failed from {ip} ({len(attempts)}/{MAX_ATTEMPTS})")
            return render_template("login.html", error="Incorrect password")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.pop("authenticated", None); return redirect("/login")


@app.before_request
def inject_pending_count():
    if request.path.startswith(("/api/", "/health", "/static/", "/unsubscribe")):
        g.pending_count = 0; return
    if session.get("authenticated"):
        try:
            g.pending_count = db.get_draft_counts().get("pending", 0)
        except Exception:
            g.pending_count = 0
    else:
        g.pending_count = 0


@app.context_processor
def utility_processor():
    return {"pending_count": getattr(g, "pending_count", 0)}


def make_unsub_token(email):
    return hmac.new(app.secret_key.encode(), email.encode(), hashlib.sha256).hexdigest()[:16]


@app.route("/unsubscribe")
def unsubscribe():
    email = request.args.get("email", ""); token = request.args.get("token", "")
    if not email: return "Invalid link", 400
    if not hmac.compare_digest(token, make_unsub_token(email)): return "Invalid or expired unsubscribe link", 403
    db.add_unsubscribe(email, token)
    db.log_action("UNSUBSCRIBE", email)
    return render_template("unsubscribed.html", email=email)


@app.errorhandler(404)
def page_not_found(e): return render_template("error.html", code=404, message="Page not found"), 404


@app.errorhandler(500)
def server_error(e): return render_template("error.html", code=500, message="Something went wrong"), 500


@app.route("/health")
def health():
    try:
        db.get_conn().execute("SELECT 1")
        return jsonify({"status": "ok", "db": "sqlite"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/")
@login_required
def overview():
    accounts = db.get_all_accounts()
    stats = {
        "total": len(accounts),
        "hot": sum(1 for a in accounts if a["tier"] == "HOT"),
        "warm": sum(1 for a in accounts if a["tier"] == "WARM"),
        "cold": sum(1 for a in accounts if a["tier"] == "COLD"),
        "banks": sum(1 for a in accounts if a["account_type"] == "BANK"),
        "digital": sum(1 for a in accounts if a["segment"] == "DIGITAL"),
        "fintech": sum(1 for a in accounts if a["account_type"] in ("FI", "VENDOR")),
    }
    dash = db.get_dashboard_stats()
    news = db.get_news_feed(limit=5)
    top_accounts = sorted(accounts, key=lambda a: a["composite_score"], reverse=True)[:10]
    return render_template(
        "overview.html", acct_stats=stats,
        contact_count=dash["contacts"].get("total") or 0,
        signal_count=dash["news"].get("unread") or 0,
        product_count=0,
        top_accounts=top_accounts, recent_signals=news,
    )


@app.route("/accounts")
@login_required
def accounts_list():
    tier_f = request.args.get("tier", ""); seg_f = request.args.get("segment", ""); search = request.args.get("q", "")
    accts = db.get_accounts_filtered(search=search, tier=tier_f, segment=seg_f)
    all_accounts = db.get_all_accounts()
    all_tiers = sorted({a["tier"] for a in all_accounts if a.get("tier")})
    all_segs = sorted({a["segment"] for a in all_accounts if a.get("segment")})
    return render_template("accounts.html", accounts=accts, search=search, tier_filter=tier_f, seg_filter=seg_f, all_tiers=all_tiers, all_segments=all_segs)


@app.route("/account/<int:aid>")
@login_required
def account_detail_page(aid):
    acct = db.get_account_by_id(aid)
    if not acct: return render_template("error.html", code=404, message="Account not found"), 404
    contacts_list = db.get_contacts_for_account(aid)
    signals_list = db.get_signals_for_account_name(acct["name"], limit=20)
    drafts_list = db.get_drafts_for_account(aid, limit=10)
    touch_history = db.get_touches_for_account(aid, limit=20)
    return render_template(
        "account_detail.html", account=acct, contacts=contacts_list,
        signals=signals_list, drafts=drafts_list, touches=touch_history,
    )


@app.route("/drafts")
@login_required
def drafts():
    sf = request.args.get("status", "pending")
    status_map = {"pending": "DRAFT", "approved": "APPROVED", "sent": "SENT", "rejected": "REJECTED"}
    conn = db.get_conn()
    if sf == "all":
        rows = conn.execute("""
            SELECT d.*, c.full_name as contact_name, c.institution as company, c.role as title,
                   c.linkedin_url, c.do_not_contact, c.email as contact_email
            FROM draft_messages d LEFT JOIN contacts c ON d.contact_id = c.id
            ORDER BY d.generated_at DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT d.*, c.full_name as contact_name, c.institution as company, c.role as title,
                   c.linkedin_url, c.do_not_contact, c.email as contact_email
            FROM draft_messages d LEFT JOIN contacts c ON d.contact_id = c.id
            WHERE d.status = ? ORDER BY d.generated_at DESC
        """, (status_map.get(sf, sf.upper()),)).fetchall()
    return render_template("drafts.html", drafts=[dict(r) for r in rows], current_filter=sf)


@app.route("/contacts")
@login_required
def contacts():
    search = request.args.get("q", ""); tier_f = request.args.get("tier", ""); type_f = request.args.get("type", "")
    rows = db.get_all_contacts(search=search, relationship_type=type_f, tier=tier_f)
    all_contacts = db.get_all_contacts()
    all_tiers = sorted({c["tier"] for c in all_contacts if c.get("tier")})
    all_types = sorted({c["relationship_type"] for c in all_contacts if c.get("relationship_type")})
    return render_template("contacts.html", contacts=rows, search=search, tier_filter=tier_f, type_filter=type_f, all_tiers=all_tiers, all_types=all_types)


@app.route("/contact/<int:cid>")
@login_required
def contact_detail(cid):
    c = db.get_contact_by_id(cid)
    if not c: return render_template("error.html", code=404, message="Contact not found"), 404
    touches = db.get_touch_history(cid)
    conn = db.get_conn()
    pending = [dict(r) for r in conn.execute(
        "SELECT * FROM draft_messages WHERE contact_id=? AND status='DRAFT'", (cid,)
    ).fetchall()]
    is_unsub = db.is_unsubscribed(c.get("email", ""))
    return render_template("contact_detail.html", contact=c, touches=touches, pending=pending, is_unsubscribed=is_unsub)


@app.route("/intelligence")
@login_required
def intelligence():
    return render_template("intelligence.html", signals=db.get_news_feed(limit=100))


@app.route("/templates")
@login_required
def templates():
    return render_template("templates.html", templates=db.get_templates())


@app.route("/audit")
@login_required
def audit():
    return render_template("audit.html", logs=db.get_audit_log(200))


@app.route("/api/draft/<int:did>/approve", methods=["POST"])
@login_required
def api_approve(did):
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False, "error": "Draft not found"}), 404
    contact = db.get_contact_by_id(draft["contact_id"])
    if contact and contact.get("do_not_contact"): return jsonify({"ok": False, "error": "Contact is marked do-not-contact"}), 400
    if contact and contact.get("email") and db.is_unsubscribed(contact["email"]):
        return jsonify({"ok": False, "error": "Contact has unsubscribed"}), 400
    db.approve_draft(did)
    db.log_action("APPROVE", f"Draft #{did}")
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/reject", methods=["POST"])
@login_required
def api_reject(did):
    notes = request.json.get("notes", "") if request.is_json else ""
    db.reject_draft(did, notes)
    db.log_action("REJECT", f"Draft #{did}: {notes}")
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/edit", methods=["POST"])
@login_required
def api_edit(did):
    data = request.json
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False}), 404
    db.update_draft_body(
        did,
        subject=data.get("subject", draft.get("subject")),
        body_en=data.get("body", draft.get("body_en")),
        body_ar=draft.get("body_ar"),
    )
    db.log_action("EDIT", f"Draft #{did}")
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/send", methods=["POST"])
@login_required
def api_send(did):
    """Manually trigger the send-approved pipeline (Mailchimp/SendGrid/Heyreach) for this one draft."""
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False, "error": "Not found"}), 404
    if draft["status"] != "APPROVED": return jsonify({"ok": False, "error": "Must be approved first"}), 400
    try:
        from abm_engine.core.orchestrator import Orchestrator
        Orchestrator()._send_draft(draft)
        db.log_action("SEND", f"Draft #{did}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Send failed: {str(e)[:150]}"}), 500


@app.route("/api/draft/<int:did>/redraft", methods=["POST"])
@login_required
def api_redraft(did):
    conn = db.get_conn()
    with conn:
        conn.execute("DELETE FROM draft_messages WHERE id=? AND status='REJECTED'", (did,))
    db.log_action("REDRAFT", f"Deleted draft #{did}")
    return jsonify({"ok": True, "message": "Draft deleted. A fresh one will be generated next cycle."})


@app.route("/api/draft/<int:did>/use-as-template", methods=["POST"])
@login_required
def api_use_as_template(did):
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False}), 404
    name = (request.json or {}).get("name", f"Template from draft #{did}")
    channel = "email" if draft.get("touch_type") == "EMAIL" else "whatsapp"
    db.save_template(None, name, channel, draft.get("subject", ""), draft.get("body_en", ""))
    db.log_action("TEMPLATE_FROM_DRAFT", f"'{name}' from #{did}")
    return jsonify({"ok": True})


@app.route("/api/contact/<int:cid>/consent", methods=["POST"])
@login_required
def api_update_consent(cid):
    d = request.json
    db.update_contact_consent(cid, d.get("consent_status", "none"), d.get("consent_source", ""))
    db.log_action("CONSENT", f"Contact #{cid}: {d.get('consent_status')}")
    return jsonify({"ok": True})


@app.route("/api/signal/<int:sid>/read", methods=["POST"])
@login_required
def api_mark_read(sid):
    db.mark_news_read(sid)
    return jsonify({"ok": True})


@app.route("/api/backup", methods=["POST"])
@login_required
def api_backup():
    try:
        filename = db.backup_db()
        db.log_action("BACKUP", filename)
        return jsonify({"ok": True, "file": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/template/save", methods=["POST"])
@login_required
def api_template_save():
    d = request.json; tid = d.get("id"); name = d.get("name", "Untitled")
    ch = d.get("channel", "email"); subj = d.get("subject", ""); body = d.get("body", "")
    db.save_template(tid, name, ch, subj, body)
    db.log_action("TEMPLATE_SAVE", name)
    return jsonify({"ok": True})


@app.route("/api/template/<int:tid>/delete", methods=["POST"])
@login_required
def api_template_delete(tid):
    db.delete_template(tid)
    db.log_action("TEMPLATE_DELETE", f"#{tid}")
    return jsonify({"ok": True})


@app.route("/api/template/<int:tid>")
@login_required
def api_template_get(tid):
    t = db.get_template_by_id(tid)
    return jsonify(t if t else {})


@app.route("/api/contacts/stats")
@login_required
def api_stats():
    return jsonify(db.get_dashboard_stats()["contacts"])


def run_dashboard(host="127.0.0.1", port=5000, debug=False):
    print(f"\n  ABM Dashboard (SQLite) | http://localhost:{port} | DB: {db.DB_PATH}\n")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_dashboard()
