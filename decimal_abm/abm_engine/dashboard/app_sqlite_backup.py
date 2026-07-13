"""
app.py — PRODUCTION-GRADE ABM Dashboard
════════════════════════════════════════
Bugs fixed: #1,3,5,6,8,10,11,14,15,16,18,19,22,23,26,27,30,31,33,34,36,37,44,45,48,49,50,52,53,54,55,56,57,63,64,65
"""
from __future__ import annotations
import os, sys, json, shutil, re, hmac, hashlib, time as _time, sqlite3
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g
from flask_cors import CORS
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "abm_engine.db"
ENV_PATH = ROOT / "abm_engine" / ".env"
BACKUP_DIR = ROOT / "backups"
load_dotenv(ENV_PATH)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "decimal-abm-CHANGE-ME-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "decimal2026")
SENDGRID_KEY = os.environ.get("SENDGRID_API_KEY", "")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM_EMAIL", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM_EMAIL", "")
UNSUBSCRIBE_BASE = os.environ.get("UNSUBSCRIBE_URL", "http://localhost:5000/unsubscribe")

LOGIN_ATTEMPTS = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300

# ── DB helpers (with context manager) ───────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def query(sql, params=(), one=False):
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return rows[0] if one and rows else rows if not one else None
    finally:
        conn.close()

def execute(sql, params=()):
    conn = get_db()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

def audit_log(action, details=""):
    try: execute("INSERT INTO audit_log (action,details,timestamp) VALUES (?,?,datetime('now'))", (action,details))
    except: pass

# ── Auth with rate limiting ─────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET","POST"])
def login():
    ip = request.remote_addr
    if request.method == "POST":
        now = _time.time()
        attempts = LOGIN_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < LOCKOUT_SECONDS]
        if len(attempts) >= MAX_ATTEMPTS:
            return render_template("login.html", error=f"Too many attempts. Try again in {int(LOCKOUT_SECONDS/60)} minutes.")
        pwd = request.form.get("password","")
        if hmac.compare_digest(pwd.encode(), DASHBOARD_PASSWORD.encode()):
            session["authenticated"] = True
            LOGIN_ATTEMPTS.pop(ip, None)
            audit_log("LOGIN", f"Successful from {ip}")
            return redirect("/")
        else:
            attempts.append(now)
            LOGIN_ATTEMPTS[ip] = attempts
            audit_log("LOGIN_FAIL", f"Failed from {ip} ({len(attempts)}/{MAX_ATTEMPTS})")
            return render_template("login.html", error="Incorrect password")
    return render_template("login.html", error=None)

@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect("/login")

# ── Pending count for ALL pages ─────────────────────────────────────────────
@app.before_request
def inject_pending_count():
    if request.path.startswith(("/api/", "/health", "/static/", "/unsubscribe")):
        g.pending_count = 0; return
    if session.get("authenticated"):
        try:
            r = query("SELECT COUNT(*) as cnt FROM drafts WHERE status='pending'", one=True)
            g.pending_count = r["cnt"] if r else 0
        except: g.pending_count = 0
    else:
        g.pending_count = 0

@app.context_processor
def utility_processor():
    return {"pending_count": getattr(g, "pending_count", 0)}

# ── Table setup ─────────────────────────────────────────────────────────────
def ensure_tables():
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER,
                channel TEXT DEFAULT 'email', subject TEXT, body TEXT,
                status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')),
                reviewed_at TEXT, sent_at TEXT, reviewer_notes TEXT,
                source TEXT DEFAULT 'ai');
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, title TEXT,
                summary TEXT, url TEXT UNIQUE, relevance TEXT,
                created_at TEXT DEFAULT (datetime('now')), is_read INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS touch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER,
                channel TEXT, subject TEXT, body TEXT, status TEXT,
                sent_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                channel TEXT DEFAULT 'email', subject TEXT, body TEXT,
                is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT,
                details TEXT, timestamp TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS unsubscribes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE,
                token TEXT, unsubscribed_at TEXT DEFAULT (datetime('now')));
        """)
        # Migrate ALL tables — add missing columns to existing tables
        migrations = {
            "drafts": {"source": "TEXT DEFAULT 'ai'"},
            "contacts": {
                "consent_status":"TEXT DEFAULT 'none'", "consent_date":"TEXT",
                "consent_source":"TEXT", "data_source":"TEXT",
                "do_not_contact":"INTEGER DEFAULT 0",
                "relationship_type":"TEXT DEFAULT 'target'",
                "persona":"TEXT", "warmness":"TEXT DEFAULT 'Cold'",
                "priority_score":"INTEGER DEFAULT 0", "tier":"TEXT DEFAULT 'COLD'",
                "current_touch":"INTEGER DEFAULT 0", "is_active":"INTEGER DEFAULT 1",
                "key_signal":"TEXT", "outreach_angle":"TEXT", "product_fit":"TEXT",
                "background_notes":"TEXT", "pitch_notes":"TEXT", "connection_paths":"TEXT",
                "linkedin_url":"TEXT", "whatsapp":"TEXT", "phone":"TEXT",
                "replied":"INTEGER DEFAULT 0",
            }
        }
        for table, cols in migrations.items():
            try:
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, typedef in cols.items():
                    if col not in existing:
                        try: conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                        except: pass
            except: pass
        conn.commit()
    finally:
        conn.close()

# ── Unsubscribe (public, token-validated) ───────────────────────────────────
def make_unsub_token(email):
    return hmac.new(app.secret_key.encode(), email.encode(), hashlib.sha256).hexdigest()[:16]

def make_unsub_url(email):
    token = make_unsub_token(email)
    return f"{UNSUBSCRIBE_BASE}?email={email}&token={token}"

@app.route("/unsubscribe")
def unsubscribe():
    email = request.args.get("email","")
    token = request.args.get("token","")
    if not email: return "Invalid link", 400
    expected = make_unsub_token(email)
    if not hmac.compare_digest(token, expected):
        return "Invalid or expired unsubscribe link", 403
    conn = get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO unsubscribes (email,token) VALUES (?,?)", (email,token))
        conn.execute("UPDATE contacts SET do_not_contact=1 WHERE email=?", (email,))
        conn.commit()
    finally: conn.close()
    audit_log("UNSUBSCRIBE", email)
    return render_template("unsubscribed.html", email=email)

# ── Actual email sending ────────────────────────────────────────────────────
def send_email(to_email, subject, body):
    if SMTP_HOST and SMTP_USER:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM or SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
        return True
    elif SENDGRID_KEY and SENDGRID_FROM:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        sg = SendGridAPIClient(SENDGRID_KEY)
        msg = Mail(from_email=SENDGRID_FROM, to_emails=to_email, subject=subject, plain_text_content=body)
        r = sg.send(msg)
        return r.status_code == 202
    return False

# ── Error pages ─────────────────────────────────────────────────────────────
@app.errorhandler(404)
def page_not_found(e):
    return render_template("error.html", code=404, message="Page not found"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, message="Something went wrong"), 500

# ── Health check ────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    try:
        query("SELECT 1", one=True)
        return jsonify({"status": "ok", "db": "connected", "timestamp": datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# ── ROUTES ──────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def overview():
    # Account-level stats
    acct_stats = query("""SELECT
        COUNT(*) as total,
        SUM(CASE WHEN tier='Tier 1' THEN 1 ELSE 0 END) as tier1,
        SUM(CASE WHEN tier='Tier 2' THEN 1 ELSE 0 END) as tier2,
        SUM(CASE WHEN tier='Tier 3' THEN 1 ELSE 0 END) as tier3,
        SUM(CASE WHEN segment='Commercial Bank' THEN 1 ELSE 0 END) as banks,
        SUM(CASE WHEN segment='Digital Bank' THEN 1 ELSE 0 END) as digital,
        SUM(CASE WHEN segment='Fintech' THEN 1 ELSE 0 END) as fintech
        FROM accounts""", one=True) or {}
    contact_count = query("SELECT COUNT(*) as cnt FROM contacts WHERE is_active=1", one=True)
    signal_count = query("SELECT COUNT(*) as cnt FROM signals", one=True)
    product_count = query("SELECT COUNT(*) as cnt FROM products", one=True)
    top_accounts = query("SELECT * FROM accounts ORDER BY score DESC, tier ASC LIMIT 10")
    recent_signals = query("""SELECT s.*, a.name as account_name
        FROM signals s LEFT JOIN accounts a ON s.account_id = a.id
        ORDER BY s.created_at DESC LIMIT 5""")
    return render_template("overview.html",
        acct_stats=acct_stats,
        contact_count=(contact_count or {}).get("cnt", 0),
        signal_count=(signal_count or {}).get("cnt", 0),
        product_count=(product_count or {}).get("cnt", 0),
        top_accounts=top_accounts,
        recent_signals=recent_signals)

@app.route("/accounts")
@login_required
def accounts_list():
    tier_f = request.args.get("tier", "")
    seg_f = request.args.get("segment", "")
    search = request.args.get("q", "")
    sql = """SELECT a.*,
        (SELECT COUNT(*) FROM contacts c WHERE c.account_id = a.id AND c.is_active=1) as contact_count,
        (SELECT COUNT(*) FROM signals s WHERE s.account_id = a.id) as signal_count,
        (SELECT COUNT(*) FROM drafts d WHERE d.account_id = a.id) as draft_count
        FROM accounts a WHERE 1=1"""
    params = []
    if search:
        sql += " AND (a.name LIKE ? OR a.segment LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if tier_f:
        sql += " AND a.tier = ?"
        params.append(tier_f)
    if seg_f:
        sql += " AND a.segment = ?"
        params.append(seg_f)
    sql += " ORDER BY a.tier ASC, a.score DESC, a.name ASC"
    accts = query(sql, params)
    all_tiers = [r["tier"] for r in query("SELECT DISTINCT tier FROM accounts WHERE tier IS NOT NULL ORDER BY tier")]
    all_segs = [r["segment"] for r in query("SELECT DISTINCT segment FROM accounts WHERE segment IS NOT NULL ORDER BY segment")]
    return render_template("accounts.html", accounts=accts, search=search,
        tier_filter=tier_f, seg_filter=seg_f, all_tiers=all_tiers, all_segments=all_segs)

@app.route("/account/<int:aid>")
@login_required
def account_detail_page(aid):
    acct = query("SELECT * FROM accounts WHERE id=?", (aid,), one=True)
    if not acct: return render_template("error.html", code=404, message="Account not found"), 404
    contacts_list = query("SELECT * FROM contacts WHERE account_id=? AND is_active=1 ORDER BY seniority, full_name", (aid,))
    signals_list = query("SELECT * FROM signals WHERE account_id=? ORDER BY created_at DESC LIMIT 20", (aid,))
    products_list = query("""SELECT p.*, pf.fit_score, pf.fit_reason, pf.pitch_angle
        FROM products p LEFT JOIN product_fit pf ON p.id = pf.product_id AND pf.account_id = ?
        ORDER BY pf.fit_score DESC""", (aid,))
    relationships_list = query("SELECT * FROM relationships WHERE to_account_id=? ORDER BY strength DESC", (aid,))
    opportunities_list = query("""SELECT o.*, p.name as product_name
        FROM opportunities o LEFT JOIN products p ON o.product_id = p.id
        WHERE o.account_id=? ORDER BY o.probability DESC""", (aid,))
    drafts_list = query("""SELECT d.*, c.full_name as contact_name
        FROM drafts d LEFT JOIN contacts c ON d.contact_id = c.id
        WHERE d.account_id=? ORDER BY d.created_at DESC LIMIT 10""", (aid,))
    touch_history = query("""SELECT t.*, c.full_name as contact_name
        FROM touch_log t LEFT JOIN contacts c ON t.contact_id = c.id
        WHERE t.account_id=? ORDER BY t.sent_at DESC LIMIT 20""", (aid,))
    return render_template("account_detail.html", account=acct,
        contacts=contacts_list, signals=signals_list, products=products_list,
        relationships=relationships_list, opportunities=opportunities_list,
        drafts=drafts_list, touches=touch_history)

@app.route("/drafts")
@login_required
def drafts():
    sf = request.args.get("status","pending")
    base = """SELECT d.*, c.full_name as contact_name, c.institution as company,
        c.role as title, c.whatsapp as whatsapp_number, c.do_not_contact, c.email as contact_email
        FROM drafts d LEFT JOIN contacts c ON d.contact_id = c.id"""
    if sf == "all":
        rows = query(f"{base} ORDER BY d.created_at DESC")
    else:
        rows = query(f"{base} WHERE d.status = ? ORDER BY d.created_at DESC", (sf,))
    return render_template("drafts.html", drafts=rows, current_filter=sf)

@app.route("/contacts")
@login_required
def contacts():
    search = request.args.get("q",""); tier_f = request.args.get("tier",""); type_f = request.args.get("type","")
    sql = "SELECT * FROM contacts WHERE is_active = 1"; params = []
    if search:
        sql += " AND (full_name LIKE ? OR institution LIKE ? OR role LIKE ?)"
        params += [f"%{search}%"] * 3
    if tier_f: sql += " AND tier = ?"; params.append(tier_f)
    if type_f: sql += " AND relationship_type = ?"; params.append(type_f)
    sql += " ORDER BY priority_score DESC"
    rows = query(sql, params)
    all_tiers = [r["tier"] for r in query("SELECT DISTINCT tier FROM contacts WHERE tier IS NOT NULL AND tier != ''")]
    all_types = [r["relationship_type"] for r in query("SELECT DISTINCT relationship_type FROM contacts WHERE relationship_type IS NOT NULL AND relationship_type != ''")]
    return render_template("contacts.html", contacts=rows, search=search,
        tier_filter=tier_f, type_filter=type_f, all_tiers=sorted(all_tiers), all_types=sorted(all_types))

@app.route("/contact/<int:cid>")
@login_required
def contact_detail(cid):
    c = query("SELECT * FROM contacts WHERE id=?", (cid,), one=True)
    if not c: return render_template("error.html", code=404, message="Contact not found"), 404
    touches = query("SELECT * FROM touch_log WHERE contact_id=? ORDER BY sent_at DESC", (cid,))
    pending = query("SELECT * FROM drafts WHERE contact_id=? AND status='pending'", (cid,))
    unsub = query("SELECT id FROM unsubscribes WHERE email=?", (c.get("email",""),), one=True) if c.get("email") else None
    return render_template("contact_detail.html", contact=c, touches=touches, pending=pending, is_unsubscribed=bool(unsub))

@app.route("/intelligence")
@login_required
def intelligence():
    signals = query("SELECT * FROM signals ORDER BY created_at DESC LIMIT 100")
    return render_template("intelligence.html", signals=signals)

@app.route("/templates")
@login_required
def templates():
    tmpls = query("SELECT * FROM templates ORDER BY updated_at DESC")
    return render_template("templates.html", templates=tmpls)

@app.route("/audit")
@login_required
def audit():
    logs = query("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 200")
    return render_template("audit.html", logs=logs)

# ── API: Drafts ─────────────────────────────────────────────────────────────
@app.route("/api/draft/<int:did>/approve", methods=["POST"])
@login_required
def api_approve(did):
    draft = query("""SELECT d.*, c.email, c.do_not_contact, c.consent_status
        FROM drafts d JOIN contacts c ON d.contact_id=c.id WHERE d.id=?""", (did,), one=True)
    if not draft: return jsonify({"ok":False,"error":"Draft not found"}), 404
    if draft.get("do_not_contact"):
        return jsonify({"ok":False,"error":"Contact is marked do-not-contact"}), 400
    if draft.get("email"):
        unsub = query("SELECT id FROM unsubscribes WHERE email=?", (draft["email"],), one=True)
        if unsub: return jsonify({"ok":False,"error":"Contact has unsubscribed"}), 400
    if draft.get("consent_status") in ("none", None) and draft.get("channel") in ("email", "whatsapp"):
        return jsonify({"ok":False,"error":"Contact has no consent recorded. Update consent status first."}), 400
    execute("UPDATE drafts SET status='approved', reviewed_at=datetime('now') WHERE id=?", (did,))
    audit_log("APPROVE", f"Draft #{did}")
    return jsonify({"ok":True})

@app.route("/api/draft/<int:did>/reject", methods=["POST"])
@login_required
def api_reject(did):
    notes = request.json.get("notes","") if request.is_json else ""
    execute("UPDATE drafts SET status='rejected', reviewed_at=datetime('now'), reviewer_notes=? WHERE id=?", (notes,did))
    audit_log("REJECT", f"Draft #{did}: {notes}")
    return jsonify({"ok":True})

@app.route("/api/draft/<int:did>/edit", methods=["POST"])
@login_required
def api_edit(did):
    data = request.json
    old = query("SELECT subject, body FROM drafts WHERE id=?", (did,), one=True)
    if data.get("body"): execute("UPDATE drafts SET body=? WHERE id=?", (data["body"],did))
    if data.get("subject"): execute("UPDATE drafts SET subject=? WHERE id=?", (data["subject"],did))
    audit_log("EDIT", f"Draft #{did} | Old subject: {(old or {}).get('subject','')[:50]}")
    return jsonify({"ok":True})

@app.route("/api/draft/<int:did>/send", methods=["POST"])
@login_required
def api_send(did):
    draft = query("""SELECT d.*, c.email as to_email, c.full_name, c.do_not_contact
        FROM drafts d JOIN contacts c ON d.contact_id=c.id WHERE d.id=?""", (did,), one=True)
    if not draft: return jsonify({"ok":False,"error":"Not found"}), 404
    if draft["status"] != "approved": return jsonify({"ok":False,"error":"Must be approved first"}), 400
    if not draft.get("to_email"): return jsonify({"ok":False,"error":"Contact has no email address"}), 400
    # Actually send the email
    try:
        success = send_email(draft["to_email"], draft["subject"] or "From Decimal Technologies", draft["body"])
        if success:
            execute("UPDATE drafts SET status='sent', sent_at=datetime('now') WHERE id=?", (did,))
            execute("INSERT INTO touch_log (contact_id,channel,subject,body,status) VALUES (?,?,?,?,'sent')",
                (draft["contact_id"],"email",draft["subject"],draft["body"]))
            execute("UPDATE contacts SET current_touch=current_touch+1 WHERE id=?", (draft["contact_id"],))
            audit_log("SEND", f"Email to {draft['full_name']} ({draft['to_email']})")
            return jsonify({"ok":True})
        else:
            execute("UPDATE drafts SET status='send_failed', reviewer_notes='Send failed - no email provider configured' WHERE id=?", (did,))
            return jsonify({"ok":False,"error":"No email provider configured (SMTP or SendGrid)"}), 500
    except Exception as e:
        execute("UPDATE drafts SET status='send_failed', reviewer_notes=? WHERE id=?", (str(e)[:200],did))
        audit_log("SEND_FAIL", f"Draft #{did}: {str(e)[:100]}")
        return jsonify({"ok":False,"error":f"Send failed: {str(e)[:100]}"}), 500

@app.route("/api/draft/<int:did>/mark-sent", methods=["POST"])
@login_required
def api_mark_sent(did):
    draft = query("SELECT * FROM drafts WHERE id=?", (did,), one=True)
    if not draft: return jsonify({"ok":False,"error":"Not found"}), 404
    execute("UPDATE drafts SET status='sent', sent_at=datetime('now') WHERE id=?", (did,))
    execute("INSERT INTO touch_log (contact_id,channel,subject,body,status) VALUES (?,?,?,?,'sent')",
        (draft["contact_id"],"whatsapp",draft["subject"],draft["body"]))
    execute("UPDATE contacts SET current_touch=current_touch+1 WHERE id=?", (draft["contact_id"],))
    audit_log("WA_SENT", f"WhatsApp draft #{did}")
    return jsonify({"ok":True})

@app.route("/api/draft/<int:did>/redraft", methods=["POST"])
@login_required
def api_redraft(did):
    execute("DELETE FROM drafts WHERE id=? AND status IN ('rejected','send_failed')", (did,))
    audit_log("REDRAFT", f"Deleted draft #{did} for regeneration")
    return jsonify({"ok":True,"message":"Draft deleted. Engine will regenerate on next cycle."})

@app.route("/api/draft/<int:did>/use-as-template", methods=["POST"])
@login_required
def api_use_as_template(did):
    draft = query("SELECT * FROM drafts WHERE id=?", (did,), one=True)
    if not draft: return jsonify({"ok":False}), 404
    name = request.json.get("name", f"Template from draft #{did}")
    body = draft["body"]
    # Strip compliance footer before saving as template
    if "\n\n---\n" in body:
        body = body.split("\n\n---\n")[0]
    execute("INSERT INTO templates (name,channel,subject,body) VALUES (?,?,?,?)",
        (name, draft["channel"], draft["subject"], body))
    audit_log("TEMPLATE_FROM_DRAFT", f"'{name}' from #{did}")
    return jsonify({"ok":True})

# ── API: Templates ──────────────────────────────────────────────────────────
@app.route("/api/template/save", methods=["POST"])
@login_required
def api_template_save():
    d = request.json
    tid = d.get("id"); name = d.get("name","Untitled")
    ch = d.get("channel","email"); subj = d.get("subject",""); body = d.get("body","")
    if tid:
        execute("UPDATE templates SET name=?,channel=?,subject=?,body=?,updated_at=datetime('now') WHERE id=?", (name,ch,subj,body,tid))
    else:
        execute("INSERT INTO templates (name,channel,subject,body) VALUES (?,?,?,?)", (name,ch,subj,body))
    audit_log("TEMPLATE_SAVE", name)
    return jsonify({"ok":True})

@app.route("/api/template/<int:tid>/delete", methods=["POST"])
@login_required
def api_template_delete(tid):
    execute("DELETE FROM templates WHERE id=?", (tid,))
    # Clean up active_template.json if it references this template
    cfg = ROOT / "abm_engine" / "active_template.json"
    if cfg.exists():
        try:
            with open(cfg) as f: data = json.load(f)
            if data.get("template_id") == tid: cfg.unlink()
        except: pass
    audit_log("TEMPLATE_DELETE", f"#{tid}")
    return jsonify({"ok":True})

@app.route("/api/template/<int:tid>")
@login_required
def api_template_get(tid):
    t = query("SELECT * FROM templates WHERE id=?", (tid,), one=True)
    return jsonify(t if t else {})

@app.route("/api/regenerate-from-template", methods=["POST"])
@login_required
def api_regenerate_from_template():
    tid = request.json.get("template_id")
    tmpl = query("SELECT * FROM templates WHERE id=?", (tid,), one=True)
    if not tmpl: return jsonify({"ok":False,"error":"Not found"}), 404
    cfg = ROOT / "abm_engine" / "active_template.json"
    with open(cfg,"w") as f:
        json.dump({"template_id":tid,"subject":tmpl["subject"],"body":tmpl["body"],"channel":tmpl["channel"]}, f)
    # Only delete AI-generated pending drafts, preserve manual ones
    execute("DELETE FROM drafts WHERE status='pending' AND source='ai'")
    audit_log("REGENERATE", f"From template #{tid}")
    return jsonify({"ok":True})

# ── API: Contacts ───────────────────────────────────────────────────────────
@app.route("/api/contact/<int:cid>/consent", methods=["POST"])
@login_required
def api_update_consent(cid):
    d = request.json
    execute("UPDATE contacts SET consent_status=?, consent_date=datetime('now'), consent_source=? WHERE id=?",
        (d.get("consent_status","none"), d.get("consent_source",""), cid))
    audit_log("CONSENT", f"Contact #{cid}: {d.get('consent_status')}")
    return jsonify({"ok":True})

@app.route("/api/signal/<int:sid>/read", methods=["POST"])
@login_required
def api_mark_read(sid):
    execute("UPDATE signals SET is_read=1 WHERE id=?", (sid,))
    return jsonify({"ok":True})

@app.route("/api/backup", methods=["POST"])
@login_required
def api_backup():
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = BACKUP_DIR / f"abm_backup_{ts}.db"
    conn = get_db()
    try:
        backup = sqlite3.connect(str(bp))
        conn.backup(backup)
        backup.close()
    finally: conn.close()
    for old in sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[10:]:
        old.unlink()
    audit_log("BACKUP", bp.name)
    return jsonify({"ok":True,"file":bp.name})

@app.route("/api/contacts/stats")
@login_required
def api_stats():
    r = query("""SELECT
        COUNT(*) as total,
        SUM(CASE WHEN tier='HOT' THEN 1 ELSE 0 END) as hot,
        SUM(CASE WHEN tier='WARM' THEN 1 ELSE 0 END) as warm,
        SUM(CASE WHEN tier='COLD' OR tier IS NULL THEN 1 ELSE 0 END) as cold
        FROM contacts WHERE is_active=1""", one=True)
    p = query("SELECT COUNT(*) as cnt FROM drafts WHERE status='pending'", one=True)
    s = query("SELECT COUNT(*) as cnt FROM drafts WHERE status='sent'", one=True)
    return jsonify({**(r or {}), "pending_drafts": (p or {}).get("cnt",0), "sent_messages": (s or {}).get("cnt",0)})

# ── Start ───────────────────────────────────────────────────────────────────
def run_dashboard(host="127.0.0.1", port=5000, debug=False):
    ensure_tables()
    print(f"\n  ╔═════════════════════════════════════════════════╗")
    print(f"  ║  ABM Dashboard (SECURED)                        ║")
    print(f"  ║  URL:      http://localhost:{port}               ║")
    print(f"  ║  Password: set DASHBOARD_PASSWORD in .env       ║")
    print(f"  ║  Health:   http://localhost:{port}/health         ║")
    print(f"  ╚═════════════════════════════════════════════════╝\n")
    app.run(host=host, port=port, debug=debug, use_reloader=False)

if __name__ == "__main__":
    run_dashboard()
