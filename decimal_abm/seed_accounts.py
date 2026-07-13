"""seed_accounts.py — Add missing columns + seed KSA accounts"""
import sqlite3

conn = sqlite3.connect("abm_engine.db")

# Add missing columns
existing = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
new_cols = {
    "name_ar":"TEXT","sub_segment":"TEXT","employees":"INTEGER",
    "assets_usd":"REAL","founded":"TEXT","digital_maturity":"INTEGER DEFAULT 5",
    "core_banking":"TEXT","open_banking":"TEXT","priority":"TEXT DEFAULT 'COLD'",
    "status":"TEXT DEFAULT 'Prospect'","score":"INTEGER DEFAULT 0",
    "owner":"TEXT DEFAULT 'Puneet'","last_signal_at":"TEXT","last_touch_at":"TEXT"
}
for col, typedef in new_cols.items():
    if col not in existing:
        try:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} {typedef}")
            print(f"  Added column: {col}")
        except: pass
conn.commit()

# Seed accounts
ACCTS = [
    ("Saudi National Bank (SNB)","Commercial Bank","Conventional","Tier 1",23000,8,"Temenos","Active","https://www.snb.com.sa"),
    ("Al Rajhi Bank","Commercial Bank","Islamic","Tier 1",20000,9,"Temenos","Active","https://www.alrajhibank.com.sa"),
    ("Riyad Bank","Commercial Bank","Conventional","Tier 1",8000,8,"Temenos","Active","https://www.riyadbank.com"),
    ("SABB","Commercial Bank","Conventional","Tier 1",5000,7,"Temenos","Active","https://www.sabb.com"),
    ("Alinma Bank","Commercial Bank","Islamic","Tier 2",4000,7,"Temenos","Active","https://www.alinma.com"),
    ("Bank Albilad","Commercial Bank","Islamic","Tier 2",4500,6,"Oracle","Planned","https://www.bankalbilad.com"),
    ("Banque Saudi Fransi","Commercial Bank","Conventional","Tier 2",3500,6,"Finastra","Planned","https://www.alfransi.com.sa"),
    ("Arab National Bank","Commercial Bank","Conventional","Tier 2",4000,6,"Temenos","Planned","https://www.anb.com.sa"),
    ("Bank AlJazira","Commercial Bank","Islamic","Tier 2",3000,5,"Oracle","Planned","https://www.baj.com.sa"),
    ("Gulf International Bank","Commercial Bank","Conventional","Tier 3",1500,5,None,"Planned","https://www.gib.com"),
    ("D360 Bank","Digital Bank","Digital-Only","Tier 1",500,10,"Mambu","Active","https://www.d360.bank"),
    ("STC Bank","Digital Bank","Digital-Only","Tier 1",400,10,"Mambu","Active","https://www.stcbank.com.sa"),
    ("Vision Bank","Digital Bank","Digital-Only","Tier 2",200,9,None,"Active",None),
    ("Tamara","Fintech","BNPL","Tier 1",1000,10,None,None,"https://www.tamara.co"),
    ("Tabby","Fintech","BNPL","Tier 1",800,10,None,None,"https://www.tabby.ai"),
    ("Lendo","Fintech","SME Lending","Tier 1",200,9,None,None,"https://www.lendo.sa"),
    ("Funding Souq","Fintech","SME Lending","Tier 2",100,8,None,None,"https://www.fundingsouq.com"),
    ("Geidea","Fintech","Payments","Tier 2",500,9,None,None,"https://www.geidea.net"),
    ("HyperPay","Fintech","Payments","Tier 2",300,9,None,None,"https://www.hyperpay.com"),
    ("Lean Technologies","Fintech","Open Banking","Tier 2",150,10,None,None,"https://www.leantech.me"),
    ("Hala","Fintech","Micro Finance","Tier 2",100,7,None,None,None),
    ("Erad","Fintech","Micro Lending","Tier 2",80,8,None,None,None),
    ("Neoleap","Fintech","Payments","Tier 3",100,8,None,None,None),
    ("PayTabs","Fintech","Payments","Tier 3",200,8,None,None,"https://www.paytabs.com"),
]

n = 0
for a in ACCTS:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO accounts (name,segment,sub_segment,tier,employees,digital_maturity,core_banking,open_banking,website) VALUES (?,?,?,?,?,?,?,?,?)", a)
        n += 1
    except Exception as e:
        print(f"  Skip: {a[0]} — {e}")

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
print(f"\n  Seeded {n} accounts. Total in database: {total}\n")

# Show what's loaded
for row in conn.execute("SELECT name, segment, tier FROM accounts ORDER BY tier, name"):
    print(f"  {row[0]:30s} {row[1] or '':20s} {row[2] or ''}") 

conn.close()
