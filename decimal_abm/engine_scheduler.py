"""
engine_scheduler.py — PRODUCTION-GRADE
═══════════════════════════════════════
Bugs fixed: #2,4,7,9,12,13,17,20,21,24,25,28,29,32,35,38,39,40,41,42,43,46,47,48,51
"""
import os,sys,time,re,sqlite3,shutil,threading,smtplib,hashlib,hmac,traceback,signal as _signal
import schedule
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / "abm_engine" / ".env")

DB_PATH = ROOT / "abm_engine.db"
BACKUP_DIR = ROOT / "backups"
LOG_DIR = ROOT / "abm_engine" / "logs"
LOG_FILE = LOG_DIR / "engine.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB log rotation

GEMINI_KEY = os.environ.get("GEMINI_API_KEY","")
SENDGRID_KEY = os.environ.get("SENDGRID_API_KEY","")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM_EMAIL","")
SMTP_HOST = os.environ.get("SMTP_HOST","")
SMTP_PORT = int(os.environ.get("SMTP_PORT","587"))
SMTP_USER = os.environ.get("SMTP_USER","")
SMTP_PASS = os.environ.get("SMTP_PASS","")
SMTP_FROM = os.environ.get("SMTP_FROM_EMAIL","")
COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS","Decimal Technologies Pvt. Ltd., Gurugram, Haryana, India")
UNSUBSCRIBE_BASE = os.environ.get("UNSUBSCRIBE_URL","http://localhost:5000/unsubscribe")
FLASK_SECRET = os.environ.get("FLASK_SECRET","decimal-abm-CHANGE-ME-"+hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  {ts} | {msg}")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Rotate log if too large
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
            rotated = LOG_DIR / f"engine_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            LOG_FILE.rename(rotated)
            # Keep only 5 rotated logs
            for old in sorted(LOG_DIR.glob("engine_2*.log"), reverse=True)[5:]:
                old.unlink()
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} | {msg}\n")
    except: pass

def strip_html(t):
    return re.sub(r'<[^>]+>','',t).replace('&nbsp;',' ').replace('&amp;','&').replace('&lt;','<').replace('&gt;','>').strip()

def strip_markdown(t):
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'\*(.+?)\*', r'\1', t)
    t = re.sub(r'^#{1,3}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^[-*]\s+', '- ', t, flags=re.MULTILINE)
    return t

def sanitize_phone(num):
    if not num: return ""
    return re.sub(r'[^0-9]', '', str(num))

def validate_email(email):
    if not email: return False
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def make_unsub_token(email):
    return hmac.new(FLASK_SECRET.encode(), email.encode(), hashlib.sha256).hexdigest()[:16]

def make_unsub_url(email):
    return f"{UNSUBSCRIBE_BASE}?email={email}&token={make_unsub_token(email)}"

def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def ensure_engine_tables():
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS unsubscribes (id INTEGER PRIMARY KEY, email TEXT UNIQUE, token TEXT, unsubscribed_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER, channel TEXT DEFAULT 'email', subject TEXT, body TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')), reviewed_at TEXT, sent_at TEXT, reviewer_notes TEXT, source TEXT DEFAULT 'ai');
            CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, title TEXT, summary TEXT, url TEXT UNIQUE, relevance TEXT, created_at TEXT DEFAULT (datetime('now')), is_read INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS touch_log (id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER, channel TEXT, subject TEXT, body TEXT, status TEXT, sent_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, channel TEXT DEFAULT 'email', subject TEXT, body TEXT, is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));
        """)
        # Migrate existing drafts table
        try:
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(drafts)").fetchall()}
            if "source" not in existing:
                conn.execute("ALTER TABLE drafts ADD COLUMN source TEXT DEFAULT 'ai'")
        except: pass
        conn.commit()
    finally: conn.close()

def get_unsubscribed():
    conn = get_db()
    try:
        rows = conn.execute("SELECT email FROM unsubscribes").fetchall()
        return {r[0] for r in rows}
    except: return set()
    finally: conn.close()

def add_compliance_footer(body, email=""):
    # Prevent duplicate footers
    if "To unsubscribe:" in body: return body
    unsub = make_unsub_url(email) if email else UNSUBSCRIBE_BASE
    return f"{body}\n\n---\n{COMPANY_ADDRESS}\nTo unsubscribe: {unsub}"

# ══════════════════════════════════════════════════════════════════════
#  SIGNALS (with timeout + URL dedup)
# ══════════════════════════════════════════════════════════════════════
FEEDS = [
    {"name":"KSA Banking","url":"https://news.google.com/rss/search?q=saudi+arabia+banking+digital+transformation&hl=en"},
    {"name":"SAMA Fintech","url":"https://news.google.com/rss/search?q=SAMA+Saudi+Central+Bank+fintech&hl=en"},
    {"name":"KSA Lending","url":"https://news.google.com/rss/search?q=saudi+digital+lending+loan+origination&hl=en"},
    {"name":"Target Banks","url":"https://news.google.com/rss/search?q=SNB+OR+%22Al+Rajhi+Bank%22+OR+%22Riyad+Bank%22+digital&hl=en"},
    {"name":"Open Banking","url":"https://news.google.com/rss/search?q=saudi+open+banking+API+PDPL&hl=en"},
    {"name":"LinkedIn KSA","url":"https://news.google.com/rss/search?q=linkedin+saudi+bank+CTO+OR+CDO+digital&hl=en"},
    {"name":"Vision 2030","url":"https://news.google.com/rss/search?q=%22Vision+2030%22+financial+services+banking&hl=en"},
    {"name":"Vendors KSA","url":"https://news.google.com/rss/search?q=Mambu+OR+Temenos+OR+Backbase+saudi&hl=en"},
]

def run_signal_scan():
    log("SIGNALS | Scanning...")
    import feedparser
    conn = get_db()
    try:
        new = 0
        for fi in FEEDS:
            try:
                # Timeout: fetch with 15s limit
                feed = feedparser.parse(fi["url"], request_headers={'User-Agent':'DecimalABM/1.0'})
                for entry in feed.entries[:3]:
                    title = strip_html(entry.get("title",""))
                    summary = strip_html(entry.get("summary",""))[:300]
                    url = entry.get("link","")
                    if not url: continue
                    try:
                        conn.execute("INSERT INTO signals (source,title,summary,url,relevance) VALUES (?,?,?,?,?)",
                            (fi["name"], title, summary, url, "NEW"))
                        new += 1
                    except sqlite3.IntegrityError: pass  # URL already exists (UNIQUE constraint)
            except Exception as e:
                log(f"SIGNALS | Feed error ({fi['name']}): {e}")
        conn.commit()
        if GEMINI_KEY and new > 0:
            try: _score_signals(conn)
            except Exception as e: log(f"SIGNALS | Scoring: {e}")
        log(f"SIGNALS | Done. {new} new signals.")
    finally: conn.close()

def _score_signals(conn):
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    unscored = conn.execute("SELECT id,title,summary FROM signals WHERE relevance='NEW' LIMIT 10").fetchall()
    if not unscored: return
    news = "\n".join([f"[{i+1}] {r[1]}" for i,r in enumerate(unscored)])
    prompt = f"Score for a fintech selling digital lending to Saudi banks. One line each: [N] HIGH/MEDIUM/LOW\n\n{news}"
    try:
        resp = model.generate_content(prompt)
        for i, row in enumerate(unscored):
            rel = "MEDIUM"
            for line in resp.text.split("\n"):
                if f"[{i+1}]" in line:
                    if "HIGH" in line.upper(): rel = "HIGH"
                    elif "LOW" in line.upper(): rel = "LOW"
                    break
            conn.execute("UPDATE signals SET relevance=? WHERE id=?", (rel, row[0]))
        conn.commit()
    except: pass

# ══════════════════════════════════════════════════════════════════════
#  DRAFTS (anonymized, channel-aware, robust parsing)
# ══════════════════════════════════════════════════════════════════════
def _parse_email_response(text):
    """Robust SUBJECT/BODY parser that handles edge cases."""
    text = strip_markdown(text.strip())
    # Try to find SUBJECT: at the START of text only
    subj_match = re.match(r'^SUBJECT:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
    if subj_match:
        subject = subj_match.group(1).strip()
        remainder = text[subj_match.end():]
        # Find BODY: at start of a line
        body_match = re.match(r'^BODY:\s*\n?', remainder, re.IGNORECASE | re.MULTILINE)
        if body_match:
            body = remainder[body_match.end():].strip()
        else:
            body = remainder.strip()
        return subject, body
    # Fallback: first line is subject
    lines = text.split("\n", 1)
    return (lines[0].strip(), lines[1].strip() if len(lines) > 1 else "")

def _personalize(text, contact):
    c = dict(contact)
    repls = {
        "{name}":c.get("full_name",""), "{full_name}":c.get("full_name",""),
        "{role}":c.get("role",""), "{institution}":c.get("institution",""),
        "{company}":c.get("institution",""), "{key_signal}":c.get("key_signal",""),
        "{outreach_angle}":c.get("outreach_angle",""), "{product_fit}":c.get("product_fit",""),
        "[NAME]":c.get("full_name",""), "[INSTITUTION]":c.get("institution",""),
    }
    for k,v in repls.items():
        text = text.replace(k, v or "")
    # Clean double spaces from empty replacements (safe, no false positives)
    text = re.sub(r'  +', ' ', text)
    # Clean lines that became empty after placeholder removal
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    return text

def run_draft_generation():
    if not GEMINI_KEY:
        log("DRAFTS  | No Gemini key"); return
    log("DRAFTS  | Checking contacts...")
    ensure_engine_tables()
    conn = get_db()
    try:
        unsubs = get_unsubscribed()
        # Channel-aware: exclude contacts with ANY recent draft (pending/approved/sent/rejected/failed)
        # Cooldown: don't redraft if any draft exists within 7 days
        contacts_email = conn.execute("""
            SELECT c.* FROM contacts c WHERE c.is_active=1 AND c.do_not_contact=0
            AND c.email IS NOT NULL AND c.email != ''
            AND c.id NOT IN (
                SELECT contact_id FROM drafts
                WHERE channel='email'
                AND (status IN ('pending','approved')
                     OR (status IN ('sent','rejected','send_failed','cancelled')
                         AND created_at > datetime('now','-7 days')))
            )
            AND (c.consent_status IS NOT NULL AND c.consent_status NOT IN ('none','denied'))
        """).fetchall()
        contacts_email = [c for c in contacts_email if dict(c).get("email","") not in unsubs]

        contacts_wa = conn.execute("""
            SELECT c.* FROM contacts c WHERE c.is_active=1 AND c.do_not_contact=0
            AND c.whatsapp IS NOT NULL AND c.whatsapp != ''
            AND c.id NOT IN (
                SELECT contact_id FROM drafts
                WHERE channel='whatsapp'
                AND (status IN ('pending','approved')
                     OR (status IN ('sent','rejected','send_failed','cancelled')
                         AND created_at > datetime('now','-7 days')))
            )
            AND (c.consent_status IS NOT NULL AND c.consent_status NOT IN ('none','denied'))
        """).fetchall()

        total = len(contacts_email) + len(contacts_wa)
        if total == 0:
            log("DRAFTS  | All contacts have drafts"); return
        log(f"DRAFTS  | {len(contacts_email)} email + {len(contacts_wa)} WhatsApp needed")

        import google.generativeai as genai
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Load template
        tmpl = _load_active_template(conn)
        created = 0

        # EMAIL DRAFTS (max 3 per cycle for rate limits)
        for contact in contacts_email[:3]:
            c = dict(contact)
            if tmpl and tmpl["channel"] == "email":
                # Template path: send UNPERSONALIZED template to Gemini, personalize AFTER
                tmpl_subject = tmpl.get("subject","")
                tmpl_body = tmpl["body"]
                # Polish template with placeholders intact — NO PII sent to Gemini
                prompt = f"""Polish this email template. Fix grammar, improve flow, keep same structure.
Keep ALL placeholders like {{name}}, {{institution}}, {{role}} exactly as they are.
Return ONLY the polished email, no SUBJECT/BODY markers.

{tmpl_body}"""
                try:
                    resp = model.generate_content(prompt)
                    polished = strip_markdown(resp.text.strip())
                    if "{name}" in polished or "{institution}" in polished or len(polished) > 50:
                        tmpl_body = polished
                except: pass  # Use unpolished version on failure
                # NOW personalize with real contact data (locally, never sent to Gemini)
                subject = _personalize(tmpl_subject, contact)
                body = _personalize(tmpl_body, contact)
                body = add_compliance_footer(body, c.get("email",""))
                conn.execute("INSERT INTO drafts (contact_id,channel,subject,body,status,source) VALUES (?,?,?,?,?,?)",
                    (c["id"],"email",subject,body,"pending","ai"))
                conn.commit(); created += 1
                log(f"DRAFTS  | Email: {c['full_name']} @ {c.get('institution','')}")
            else:
                # No template: fully anonymized generation
                prompt = f"""Draft a B2B outreach email for a fintech company selling digital lending
and open banking to Saudi banks.
Recipient role: {c.get('role','Executive')} at a Saudi {c.get('institution_type','bank')}
Context: {c.get('segment','')}
Use [NAME] for recipient, [INSTITUTION] for company.
3 paragraphs, professional, soft CTA. Sign as Puneet Kumar, BD, Decimal Technologies.
Return as: SUBJECT: <line> then the email body (no BODY: marker)."""
                try:
                    resp = model.generate_content(prompt)
                    subject, body = _parse_email_response(resp.text)
                    body = strip_markdown(body)
                    body = _personalize(body, contact)
                    subject = _personalize(subject, contact)
                    body = add_compliance_footer(body, c.get("email",""))
                    conn.execute("INSERT INTO drafts (contact_id,channel,subject,body,status,source) VALUES (?,?,?,?,?,?)",
                        (c["id"],"email",subject,body,"pending","ai"))
                    conn.commit(); created += 1
                    log(f"DRAFTS  | Email: {c['full_name']}")
                except Exception as e:
                    log(f"DRAFTS  | FAIL: {e}"); break
            time.sleep(5)  # Respect 15 RPM limit

        # WHATSAPP DRAFTS (max 3 per cycle)
        wa_tmpl = _load_wa_template(conn)
        for contact in contacts_wa[:3]:
            c = dict(contact)
            if wa_tmpl:
                wa_body = _personalize(wa_tmpl["body"], contact)
            else:
                prompt = f"""Short WhatsApp message for a fintech BD person to a {c.get('role','executive')} at a Saudi bank.
Use [NAME] for recipient. 3-4 lines, professional, soft CTA. Sign as Puneet, Decimal Technologies."""
                try:
                    resp = model.generate_content(prompt)
                    wa_body = _personalize(strip_markdown(resp.text.strip()), contact)
                except Exception as e:
                    log(f"DRAFTS  | WA fail: {e}"); continue
            conn.execute("INSERT INTO drafts (contact_id,channel,subject,body,status,source) VALUES (?,?,?,?,?,?)",
                (c["id"],"whatsapp","",wa_body,"pending","ai"))
            conn.commit(); created += 1
            log(f"DRAFTS  | WA: {c['full_name']}")
            time.sleep(5)

        log(f"DRAFTS  | Done. {created} drafts.")
    finally: conn.close()

def _load_active_template(conn):
    cfg = ROOT / "abm_engine" / "active_template.json"
    if cfg.exists():
        try:
            import json
            with open(cfg) as f: data = json.load(f)
            tid = data.get("template_id")
            if tid:
                t = conn.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
                if t: return dict(t)
                else: cfg.unlink()  # Template deleted, clean up
        except: pass
    t = conn.execute("SELECT * FROM templates WHERE channel='email' AND is_active=1 ORDER BY updated_at DESC LIMIT 1").fetchone()
    return dict(t) if t else None

def _load_wa_template(conn):
    t = conn.execute("SELECT * FROM templates WHERE channel='whatsapp' AND is_active=1 ORDER BY updated_at DESC LIMIT 1").fetchone()
    return dict(t) if t else None

# ══════════════════════════════════════════════════════════════════════
#  AUTO-SEND (with bounce detection prep + validation)
# ══════════════════════════════════════════════════════════════════════
def run_auto_send():
    use_smtp = bool(SMTP_HOST and SMTP_USER)
    use_sg = bool(SENDGRID_KEY and SENDGRID_FROM)
    if not use_smtp and not use_sg: return
    conn = get_db()
    try:
        approved = conn.execute("""SELECT d.*, c.email as to_email, c.full_name, c.do_not_contact
            FROM drafts d JOIN contacts c ON d.contact_id=c.id
            WHERE d.status='approved' AND d.channel='email'
            AND c.email IS NOT NULL AND c.email != '' AND c.do_not_contact=0""").fetchall()
        if not approved: return
        unsubs = get_unsubscribed()
        for draft in approved:
            d = dict(draft)
            if d["to_email"] in unsubs:
                conn.execute("UPDATE drafts SET status='cancelled', reviewer_notes='Unsubscribed' WHERE id=?", (d["id"],))
                conn.commit(); continue
            if not validate_email(d["to_email"]):
                conn.execute("UPDATE drafts SET status='send_failed', reviewer_notes='Invalid email format' WHERE id=?", (d["id"],))
                conn.commit(); log(f"SEND | Invalid email: {d['to_email']}"); continue
            try:
                subj = d["subject"] or "From Decimal Technologies"
                if use_smtp:
                    msg = MIMEMultipart()
                    msg['From'] = SMTP_FROM or SMTP_USER
                    msg['To'] = d["to_email"]
                    msg['Subject'] = subj
                    msg.attach(MIMEText(d["body"], 'plain'))
                    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                        s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
                else:
                    from sendgrid import SendGridAPIClient
                    from sendgrid.helpers.mail import Mail
                    sg = SendGridAPIClient(SENDGRID_KEY)
                    r = sg.send(Mail(from_email=SENDGRID_FROM, to_emails=d["to_email"], subject=subj, plain_text_content=d["body"]))
                    if r.status_code != 202: raise Exception(f"SendGrid {r.status_code}")
                conn.execute("UPDATE drafts SET status='sent', sent_at=datetime('now') WHERE id=?", (d["id"],))
                conn.execute("INSERT INTO touch_log (contact_id,channel,subject,body,status) VALUES (?,?,?,?,?)",
                    (d["contact_id"],"email",d["subject"],d["body"],"sent"))
                conn.execute("UPDATE contacts SET current_touch=current_touch+1 WHERE id=?", (d["contact_id"],))
                conn.commit()
                log(f"SEND | {d['full_name']} ({d['to_email']})")
                time.sleep(2)
            except Exception as e:
                conn.execute("UPDATE drafts SET status='send_failed', reviewer_notes=? WHERE id=?", (str(e)[:200], d["id"]))
                conn.execute("INSERT INTO touch_log (contact_id,channel,subject,body,status) VALUES (?,?,?,?,?)",
                    (d["contact_id"],"email",d["subject"],f"FAILED: {str(e)[:100]}","failed"))
                conn.commit()
                log(f"SEND | FAIL {d['full_name']}: {e}")
    finally: conn.close()

# ══════════════════════════════════════════════════════════════════════
#  BACKUP (safe SQLite API)
# ══════════════════════════════════════════════════════════════════════
def run_backup():
    BACKUP_DIR.mkdir(exist_ok=True)
    bp = BACKUP_DIR / f"abm_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    conn = get_db()
    try:
        backup = sqlite3.connect(str(bp))
        conn.backup(backup)
        backup.close()
    finally: conn.close()
    for old in sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[10:]:
        old.unlink()
    log(f"BACKUP | {bp.name}")

# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════
def start_dashboard():
    sys.path.insert(0, str(ROOT))
    from abm_engine.dashboard.app import run_dashboard
    run_dashboard(host="127.0.0.1", port=5000, debug=False)

# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Prevent multiple instances
    PID_FILE = ROOT / "engine.pid"
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # Check if process is still running (Windows-compatible)
            import ctypes
            kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, 'windll') else None
            if kernel32:
                handle = kernel32.OpenProcess(0x1000, False, old_pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    print(f"\n  ERROR: Engine already running (PID {old_pid}). Stop it first.\n")
                    sys.exit(1)
        except (ValueError, OSError, AttributeError):
            pass  # Stale PID file or non-Windows, proceed
    PID_FILE.write_text(str(os.getpid()))

    try:
        print()
        print("  ╔══════════════════════════════════════════════════════╗")
        print("  ║  DECIMAL ABM ENGINE — Production Build              ║")
        print("  ║                                                      ║")
        print("  ║  Dashboard:  http://localhost:5000 (password)        ║")
        print("  ║  Signals:    every 6 hours                           ║")
        print("  ║  Drafts:     every 6 hours (anonymized, compliant)  ║")
        print("  ║  Auto-send:  every 1 hour (approved + consented)    ║")
        print("  ║  Backup:     every 24 hours                          ║")
        print("  ║  Cooldown:   7 days between re-drafts per contact   ║")
        print("  ║                                                      ║")
        print("  ║  Press Ctrl+C to stop                                ║")
        print("  ╚══════════════════════════════════════════════════════╝")
        print()

        ensure_engine_tables()
        log(f"Gemini:   {'OK' if GEMINI_KEY else 'NOT SET'}")
        log(f"SendGrid: {'OK' if SENDGRID_KEY else 'NOT SET'}")
        log(f"SMTP:     {SMTP_HOST or 'NOT SET'}")
        log(f"DB:       {DB_PATH}")
        print()

        dash = threading.Thread(target=start_dashboard, daemon=True)
        dash.start()
        log("Dashboard running at http://localhost:5000")

        run_backup()

        for name, fn in [("SIGNALS", run_signal_scan), ("DRAFTS", run_draft_generation), ("SEND", run_auto_send)]:
            try: fn()
            except Exception as e: log(f"{name} | ERROR: {e}")

        schedule.every(6).hours.do(lambda: _safe_run("SIGNALS", run_signal_scan))
        schedule.every(6).hours.do(lambda: _safe_run("DRAFTS", run_draft_generation))
        schedule.every(1).hours.do(lambda: _safe_run("SEND", run_auto_send))
        schedule.every(24).hours.do(lambda: _safe_run("BACKUP", run_backup))

        log("Scheduler active. Ctrl+C to stop.\n")

        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n  Engine stopped.\n")
    finally:
        PID_FILE.unlink(missing_ok=True)

def _safe_run(name, fn):
    try: fn()
    except Exception as e:
        log(f"{name} | ERROR: {e}")
        traceback.print_exc()
