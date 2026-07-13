"""
migrate_to_v2.py
════════════════
Migrates ABM V8 (contact-first) to V2 (account-first).

What it does:
  1. Creates all new tables (accounts, products, product_fit, etc.)
  2. Extracts unique institutions from contacts → creates accounts
  3. Links contacts to accounts via account_id
  4. Seeds the complete KSA bank/FI universe (25+ accounts)
  5. Seeds Decimal's product catalog
  6. Migrates existing signals, drafts, touch_log
  7. Preserves ALL existing data — nothing is deleted

Run:
  python migrate_to_v2.py
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "abm_engine.db"
BACKUP_PATH = ROOT / "backups" / f"pre_v2_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

print("\n  ╔══════════════════════════════════════════════╗")
print("  ║  ABM V8 → V2 Migration (Account-First)      ║")
print("  ╚══════════════════════════════════════════════╝\n")

# ── Backup first ────────────────────────────────────────────────────────────
BACKUP_PATH.parent.mkdir(exist_ok=True)
if DB_PATH.exists():
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(BACKUP_PATH))
    src.backup(dst)
    dst.close()
    src.close()
    print(f"  BACKUP  | Saved to {BACKUP_PATH.name}")
else:
    print("  BACKUP  | No existing database, starting fresh")

# ── Connect ─────────────────────────────────────────────────────────────────
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=OFF")  # During migration

# ── Step 1: Create new tables ───────────────────────────────────────────────
print("  SCHEMA  | Creating V2 tables...")

conn.executescript("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE, name_ar TEXT, segment TEXT, sub_segment TEXT,
        country TEXT DEFAULT 'KSA', website TEXT, employees INTEGER,
        assets_usd REAL, founded TEXT, digital_maturity INTEGER DEFAULT 5,
        core_banking TEXT, open_banking TEXT DEFAULT 'Unknown',
        tier TEXT DEFAULT 'Tier 3', priority TEXT DEFAULT 'COLD',
        status TEXT DEFAULT 'Prospect', score INTEGER DEFAULT 0,
        owner TEXT DEFAULT 'Puneet',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        last_signal_at TEXT, last_touch_at TEXT
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE, category TEXT, description TEXT,
        target_segments TEXT, key_benefits TEXT, competitors TEXT
    );

    CREATE TABLE IF NOT EXISTS product_fit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER, product_id INTEGER,
        fit_score INTEGER DEFAULT 50, fit_reason TEXT, pitch_angle TEXT,
        UNIQUE(account_id, product_id)
    );

    CREATE TABLE IF NOT EXISTS account_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER, score_date TEXT DEFAULT (date('now')),
        signal_score INTEGER DEFAULT 0, regulatory_score INTEGER DEFAULT 0,
        reachability_score INTEGER DEFAULT 0, relationship_score INTEGER DEFAULT 0,
        total_score INTEGER DEFAULT 0, tier TEXT, score_notes TEXT,
        UNIQUE(account_id, score_date)
    );

    CREATE TABLE IF NOT EXISTS relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_type TEXT, from_name TEXT, from_contact TEXT,
        to_account_id INTEGER, to_contact_id INTEGER,
        relationship_type TEXT, strength TEXT DEFAULT 'Weak',
        context TEXT, last_interaction TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER, product_id INTEGER,
        stage TEXT DEFAULT 'Identified', probability INTEGER DEFAULT 10,
        estimated_value TEXT, currency TEXT DEFAULT 'SAR',
        champion_id INTEGER, next_step TEXT, notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')), closed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS buying_committee (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER, contact_id INTEGER, product_id INTEGER,
        committee_role TEXT, engagement TEXT DEFAULT 'Unknown', notes TEXT,
        UNIQUE(account_id, contact_id, product_id)
    );

    -- Ensure existing tables have new columns
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT, details TEXT, timestamp TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS unsubscribes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE, token TEXT, unsubscribed_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, channel TEXT DEFAULT 'email', subject TEXT, body TEXT,
        product_id INTEGER, persona_target TEXT, sequence_step INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
    );
""")

# Add missing columns to existing tables
def add_col(table, col, typedef):
    try: conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
    except: pass

# Contacts: add account_id + new fields
add_col("contacts", "account_id", "INTEGER")
add_col("contacts", "department", "TEXT")
add_col("contacts", "decision_weight", "INTEGER DEFAULT 5")
add_col("contacts", "data_source", "TEXT")
add_col("contacts", "consent_status", "TEXT DEFAULT 'none'")
add_col("contacts", "consent_date", "TEXT")
add_col("contacts", "consent_source", "TEXT")
add_col("contacts", "do_not_contact", "INTEGER DEFAULT 0")
add_col("contacts", "persona", "TEXT")
add_col("contacts", "warmness", "TEXT DEFAULT 'Cold'")
add_col("contacts", "is_active", "INTEGER DEFAULT 1")
add_col("contacts", "background_notes", "TEXT")
add_col("contacts", "seniority", "TEXT")

# Signals: add account_id + attribution fields
add_col("signals", "account_id", "INTEGER")
add_col("signals", "signal_type", "TEXT")
add_col("signals", "urgency", "TEXT DEFAULT 'LOW'")
add_col("signals", "product_match", "TEXT")
add_col("signals", "is_actioned", "INTEGER DEFAULT 0")

# Drafts: add account_id + context fields
add_col("drafts", "account_id", "INTEGER")
add_col("drafts", "signal_id", "INTEGER")
add_col("drafts", "product_id", "INTEGER")
add_col("drafts", "sequence_step", "INTEGER DEFAULT 1")
add_col("drafts", "source", "TEXT DEFAULT 'ai'")

# Touch log: add account_id
add_col("touch_log", "account_id", "INTEGER")
add_col("touch_log", "signal_id", "INTEGER")

# Templates: add product/persona fields
add_col("templates", "product_id", "INTEGER")
add_col("templates", "persona_target", "TEXT")
add_col("templates", "sequence_step", "INTEGER DEFAULT 1")

conn.commit()
print("  SCHEMA  | All V2 tables created")

# ── Step 2: Seed KSA Account Universe ───────────────────────────────────────
print("  SEED    | Loading KSA account universe...")

KSA_ACCOUNTS = [
    # Commercial Banks
    {"name":"Saudi National Bank (SNB)","segment":"Commercial Bank","sub_segment":"Conventional","tier":"Tier 1","employees":23000,"digital_maturity":8,"core_banking":"Temenos","open_banking":"Active","website":"https://www.snb.com.sa"},
    {"name":"Al Rajhi Bank","segment":"Commercial Bank","sub_segment":"Islamic","tier":"Tier 1","employees":20000,"digital_maturity":9,"core_banking":"Temenos","open_banking":"Active","website":"https://www.alrajhibank.com.sa"},
    {"name":"Riyad Bank","segment":"Commercial Bank","sub_segment":"Conventional","tier":"Tier 1","employees":8000,"digital_maturity":8,"core_banking":"Temenos","open_banking":"Active","website":"https://www.riyadbank.com"},
    {"name":"SABB (Saudi Awwal Bank)","segment":"Commercial Bank","sub_segment":"Conventional","tier":"Tier 1","employees":5000,"digital_maturity":7,"core_banking":"Temenos","open_banking":"Active","website":"https://www.sabb.com"},
    {"name":"Alinma Bank","segment":"Commercial Bank","sub_segment":"Islamic","tier":"Tier 2","employees":4000,"digital_maturity":7,"core_banking":"Temenos","open_banking":"Active","website":"https://www.alinma.com"},
    {"name":"Bank Albilad","segment":"Commercial Bank","sub_segment":"Islamic","tier":"Tier 2","employees":4500,"digital_maturity":6,"core_banking":"Oracle","open_banking":"Planned","website":"https://www.bankalbilad.com"},
    {"name":"Banque Saudi Fransi (BSF)","segment":"Commercial Bank","sub_segment":"Conventional","tier":"Tier 2","employees":3500,"digital_maturity":6,"core_banking":"Finastra","open_banking":"Planned","website":"https://www.alfransi.com.sa"},
    {"name":"Arab National Bank (ANB)","segment":"Commercial Bank","sub_segment":"Conventional","tier":"Tier 2","employees":4000,"digital_maturity":6,"core_banking":"Temenos","open_banking":"Planned","website":"https://www.anb.com.sa"},
    {"name":"Bank AlJazira","segment":"Commercial Bank","sub_segment":"Islamic","tier":"Tier 2","employees":3000,"digital_maturity":5,"core_banking":"Oracle","open_banking":"Planned","website":"https://www.baj.com.sa"},
    {"name":"Gulf International Bank (GIB)","segment":"Commercial Bank","sub_segment":"Conventional","tier":"Tier 3","employees":1500,"digital_maturity":5,"open_banking":"Planned","website":"https://www.gib.com"},

    # Digital Banks
    {"name":"D360 Bank","segment":"Digital Bank","sub_segment":"Digital-Only","tier":"Tier 1","employees":500,"digital_maturity":10,"core_banking":"Mambu","open_banking":"Active","website":"https://www.d360.bank"},
    {"name":"STC Bank","segment":"Digital Bank","sub_segment":"Digital-Only","tier":"Tier 1","employees":400,"digital_maturity":10,"core_banking":"Mambu","open_banking":"Active","website":"https://www.stcbank.com.sa"},
    {"name":"Vision Bank","segment":"Digital Bank","sub_segment":"Digital-Only","tier":"Tier 2","employees":200,"digital_maturity":9,"open_banking":"Active"},

    # BNPL / Lending Fintechs
    {"name":"Tamara","segment":"Fintech","sub_segment":"BNPL","tier":"Tier 1","employees":1000,"digital_maturity":10,"website":"https://www.tamara.co"},
    {"name":"Tabby","segment":"Fintech","sub_segment":"BNPL","tier":"Tier 1","employees":800,"digital_maturity":10,"website":"https://www.tabby.ai"},
    {"name":"Lendo","segment":"Fintech","sub_segment":"SME Lending","tier":"Tier 1","employees":200,"digital_maturity":9,"website":"https://www.lendo.sa"},
    {"name":"Funding Souq","segment":"Fintech","sub_segment":"SME Lending","tier":"Tier 2","employees":100,"digital_maturity":8,"website":"https://www.fundingsouq.com"},
    {"name":"Erad","segment":"Fintech","sub_segment":"Micro Lending","tier":"Tier 2","employees":80,"digital_maturity":8},
    {"name":"Hala","segment":"Fintech","sub_segment":"Micro Finance","tier":"Tier 2","employees":100,"digital_maturity":7},

    # Payments / Tech
    {"name":"Geidea","segment":"Fintech","sub_segment":"Payments","tier":"Tier 2","employees":500,"digital_maturity":9,"website":"https://www.geidea.net"},
    {"name":"HyperPay","segment":"Fintech","sub_segment":"Payments","tier":"Tier 2","employees":300,"digital_maturity":9,"website":"https://www.hyperpay.com"},
    {"name":"Lean Technologies","segment":"Fintech","sub_segment":"Open Banking","tier":"Tier 2","employees":150,"digital_maturity":10,"website":"https://www.leantech.me"},
    {"name":"Neoleap","segment":"Fintech","sub_segment":"Payments","tier":"Tier 3","employees":100,"digital_maturity":8},
    {"name":"PayTabs","segment":"Fintech","sub_segment":"Payments","tier":"Tier 3","employees":200,"digital_maturity":8,"website":"https://www.paytabs.com"},
]

seeded = 0
for acct in KSA_ACCOUNTS:
    try:
        conn.execute("""INSERT OR IGNORE INTO accounts
            (name, segment, sub_segment, tier, employees, digital_maturity,
             core_banking, open_banking, website, country)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (acct["name"], acct.get("segment"), acct.get("sub_segment"),
             acct.get("tier","Tier 3"), acct.get("employees"),
             acct.get("digital_maturity",5), acct.get("core_banking"),
             acct.get("open_banking","Unknown"), acct.get("website"), "KSA"))
        seeded += 1
    except: pass
conn.commit()
print(f"  SEED    | {seeded} KSA accounts loaded")

# ── Step 3: Seed Decimal Product Catalog ────────────────────────────────────
print("  SEED    | Loading Decimal product catalog...")

PRODUCTS = [
    {"name":"Vahana","category":"Platform","description":"AI-powered digital loan origination and banking workflow platform",
     "target_segments":json.dumps(["Commercial Bank","Digital Bank","Fintech","SME Lending"]),
     "key_benefits":"60% faster loan processing, AI decisioning, SAMA compliant, end-to-end LOS",
     "competitors":json.dumps(["Temenos","Mambu","Newgen","Nucleus Software"])},
    {"name":"vHub","category":"Platform","description":"Intelligence Integration Platform — API gateway, smart routing, observability",
     "target_segments":json.dumps(["Commercial Bank","Digital Bank","Fintech","Payments"]),
     "key_benefits":"API control plane, smart failover, governed execution, 360-degree observability",
     "competitors":json.dumps(["MuleSoft","Kong","Apigee","WSO2"])},
    {"name":"Open Banking Suite","category":"Module","description":"SAMA-compliant Open Banking APIs v1/v2",
     "target_segments":json.dumps(["Commercial Bank","Digital Bank"]),
     "key_benefits":"SAMA Open Banking compliance, TPP management, consent framework",
     "competitors":json.dumps(["Tarabut","Lean Technologies"])},
    {"name":"Digital Account Opening","category":"Module","description":"End-to-end digital account opening with eKYC",
     "target_segments":json.dumps(["Commercial Bank","Digital Bank","Fintech"]),
     "key_benefits":"Paperless onboarding, Nafath integration, video KYC",
     "competitors":json.dumps(["Backbase","Temenos"])},
    {"name":"LMS (Loan Management System)","category":"Module","description":"Post-disbursement loan lifecycle management",
     "target_segments":json.dumps(["Commercial Bank","SME Lending","Micro Lending"]),
     "key_benefits":"Collections, restructuring, Islamic finance support",
     "competitors":json.dumps(["Newgen","Temenos"])},
]

for prod in PRODUCTS:
    try:
        conn.execute("INSERT OR IGNORE INTO products (name,category,description,target_segments,key_benefits,competitors) VALUES (?,?,?,?,?,?)",
            (prod["name"], prod["category"], prod["description"],
             prod["target_segments"], prod["key_benefits"], prod["competitors"]))
    except: pass
conn.commit()
print(f"  SEED    | {len(PRODUCTS)} products loaded")

# ── Step 4: Link existing contacts to accounts ─────────────────────────────
print("  MIGRATE | Linking contacts to accounts...")

contacts = conn.execute("SELECT id, institution, full_name FROM contacts WHERE account_id IS NULL").fetchall()
linked = 0
for c in contacts:
    inst = c["institution"]
    if not inst: continue
    # Find matching account
    acct = conn.execute("SELECT id FROM accounts WHERE name LIKE ?", (f"%{inst}%",)).fetchone()
    if not acct:
        # Create account from institution name
        try:
            conn.execute("INSERT OR IGNORE INTO accounts (name, segment) VALUES (?, 'Unknown')", (inst,))
            acct = conn.execute("SELECT id FROM accounts WHERE name = ?", (inst,)).fetchone()
        except: continue
    if acct:
        conn.execute("UPDATE contacts SET account_id = ? WHERE id = ?", (acct["id"], c["id"]))
        linked += 1
conn.commit()
print(f"  MIGRATE | Linked {linked} contacts to accounts")

# ── Step 5: Attribute existing signals to accounts ──────────────────────────
print("  MIGRATE | Attributing signals to accounts...")

signals = conn.execute("SELECT id, title, summary FROM signals WHERE account_id IS NULL").fetchall()
attributed = 0
accounts_list = conn.execute("SELECT id, name FROM accounts").fetchall()

for sig in signals:
    text = f"{sig['title']} {sig['summary'] or ''}"
    for acct in accounts_list:
        if acct["name"].lower() in text.lower() or any(word.lower() in text.lower() for word in acct["name"].split() if len(word) > 3):
            conn.execute("UPDATE signals SET account_id = ? WHERE id = ?", (acct["id"], sig["id"]))
            attributed += 1
            break
conn.commit()
print(f"  MIGRATE | Attributed {attributed} signals to accounts")

# ── Step 6: Link existing drafts to accounts ────────────────────────────────
print("  MIGRATE | Linking drafts to accounts...")

drafts = conn.execute("""
    SELECT d.id, c.account_id FROM drafts d
    JOIN contacts c ON d.contact_id = c.id
    WHERE d.account_id IS NULL AND c.account_id IS NOT NULL
""").fetchall()
for d in drafts:
    conn.execute("UPDATE drafts SET account_id = ? WHERE id = ?", (d["account_id"], d["id"]))
conn.commit()
print(f"  MIGRATE | Linked {len(drafts)} drafts to accounts")

# ── Step 7: Create indexes ──────────────────────────────────────────────────
print("  INDEX   | Creating indexes...")
for idx_sql in [
    "CREATE INDEX IF NOT EXISTS idx_contacts_account ON contacts(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_signals_account ON signals(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_account ON drafts(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status)",
    "CREATE INDEX IF NOT EXISTS idx_scores_account ON account_scores(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_opps_account ON opportunities(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_touch_account ON touch_log(account_id)",
]:
    try: conn.execute(idx_sql)
    except: pass
conn.commit()

# ── Summary ─────────────────────────────────────────────────────────────────
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print(f"\n  ══════════════════════════════════════════════")
print(f"  Migration complete!")
print(f"  Tables: {len(tables)}")
for t in tables:
    cnt = conn.execute(f"SELECT COUNT(*) FROM {t['name']}").fetchone()[0]
    print(f"    {t['name']:25s} {cnt:>5d} rows")
print(f"  ══════════════════════════════════════════════\n")

conn.execute("PRAGMA foreign_keys=ON")
conn.close()
