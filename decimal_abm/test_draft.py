"""
test_draft.py — Generates drafts using Gemini (ALIGNED with security model)
Anonymizes data, adds compliance footer, checks do_not_contact.
"""
import os, sys, sqlite3, re, hmac, hashlib
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / "abm_engine" / ".env")
DB_PATH = ROOT / "abm_engine.db"
API_KEY = os.environ.get("GEMINI_API_KEY","")
COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS","Decimal Technologies Pvt. Ltd., Gurugram, Haryana, India")
UNSUBSCRIBE_BASE = os.environ.get("UNSUBSCRIBE_URL","http://localhost:5000/unsubscribe")
FLASK_SECRET = os.environ.get("FLASK_SECRET","decimal-abm-CHANGE-ME-"+hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])

if not API_KEY: print("  ERROR: No GEMINI_API_KEY"); sys.exit(1)

def make_unsub_url(email):
    token = hmac.new(FLASK_SECRET.encode(), email.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{UNSUBSCRIBE_BASE}?email={email}&token={token}"

def add_footer(body, email=""):
    if "To unsubscribe:" in body: return body
    return f"{body}\n\n---\n{COMPANY_ADDRESS}\nTo unsubscribe: {make_unsub_url(email)}" if email else body

def strip_md(t):
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'\*(.+?)\*', r'\1', t)
    t = re.sub(r'^#{1,3}\s+', '', t, flags=re.MULTILINE)
    return t

conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
conn.execute("""CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER, channel TEXT DEFAULT 'email', subject TEXT, body TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')), reviewed_at TEXT, sent_at TEXT, reviewer_notes TEXT, source TEXT DEFAULT 'ai')""")
conn.execute("""CREATE TABLE IF NOT EXISTS unsubscribes (id INTEGER PRIMARY KEY, email TEXT UNIQUE, token TEXT, unsubscribed_at TEXT)""")
conn.commit()

contacts = conn.execute("SELECT * FROM contacts WHERE is_active=1 AND do_not_contact=0").fetchall()
unsubs = {r[0] for r in conn.execute("SELECT email FROM unsubscribes").fetchall()}
contacts = [c for c in contacts if dict(c).get("email","") not in unsubs]

if not contacts: print("  No eligible contacts."); sys.exit(0)
print(f"\n  {len(contacts)} contacts. Generating drafts...\n")

import google.generativeai as genai
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")
created = 0

for contact in contacts:
    c = dict(contact)
    existing = conn.execute("SELECT id FROM drafts WHERE contact_id=? AND channel='email' AND status IN ('pending','approved')", (c['id'],)).fetchone()
    if existing: print(f"  skip  {c.get('full_name','')}"); continue

    # ANONYMIZED prompt — no real names sent to Gemini
    prompt = f"""Draft a B2B outreach email for a fintech company selling digital lending to Saudi banks.
Recipient: {c.get('role','Executive')} at a Saudi {c.get('institution_type','bank')}
Use [NAME] for recipient, [INSTITUTION] for company.
3 paragraphs, professional, sign as Puneet Kumar, BD, Decimal Technologies.
Return as SUBJECT: <line> then the email body."""

    try:
        print(f"  draft  {c.get('full_name','')}...", end=" ", flush=True)
        resp = model.generate_content(prompt)
        text = strip_md(resp.text)
        subj_m = re.match(r'^SUBJECT:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
        if subj_m:
            subject = subj_m.group(1).strip()
            body = text[subj_m.end():].strip()
            body = re.sub(r'^BODY:\s*\n?', '', body, flags=re.IGNORECASE).strip()
        else:
            lines = text.split("\n",1)
            subject, body = lines[0], lines[1] if len(lines)>1 else ""

        # Personalize locally
        name = c.get("full_name",""); inst = c.get("institution","")
        body = body.replace("[NAME]",name).replace("[INSTITUTION]",inst).replace("{name}",name).replace("{institution}",inst)
        subject = subject.replace("[NAME]",name).replace("[INSTITUTION]",inst).replace("{name}",name).replace("{institution}",inst)
        body = add_footer(body, c.get("email",""))

        conn.execute("INSERT INTO drafts (contact_id,channel,subject,body,status,source) VALUES (?,?,?,?,?,?)",
            (c['id'],'email',subject,body,'pending','ai'))
        conn.commit(); created += 1; print("OK")
    except Exception as e:
        print(f"FAIL: {e}"); continue

conn.close()
print(f"\n  {created} drafts created. Open http://localhost:5000/drafts\n")
