"""
migrate_sqlite_to_pg.py — One-time SQLite → PostgreSQL migration
Run: set PG_PASSWORD=Puneet123@ && python migrate_sqlite_to_pg.py
"""
import sqlite3, os, sys
from pathlib import Path
import psycopg2, psycopg2.extras

SQLITE_PATH = Path(r"C:\Users\Puneet\Desktop\decimal_abm\abm_engine.db")

PG = {
    "host": os.environ.get("PG_HOST","localhost"),
    "port": int(os.environ.get("PG_PORT","5432")),
    "dbname": os.environ.get("PG_DBNAME","abm_engine"),
    "user": os.environ.get("PG_USER","postgres"),
    "password": os.environ.get("PG_PASSWORD","postgres"),
}

def bv(v): return bool(v) if v is not None else None

def run():
    if not SQLITE_PATH.exists():
        print(f"SQLite not found: {SQLITE_PATH}"); sys.exit(1)
    sq = sqlite3.connect(str(SQLITE_PATH)); sq.row_factory = sqlite3.Row
    pg = psycopg2.connect(**PG)
    tables = [r[0] for r in sq.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"Source tables: {', '.join(tables)}\n")

    if "accounts" in tables:
        rows = [dict(r) for r in sq.execute("SELECT * FROM accounts").fetchall()]
        cur = pg.cursor(); n = 0
        for r in rows:
            try:
                cur.execute("INSERT INTO accounts (name,account_type,segment,country,website,description,has_warm_contact,sama_pressure,is_greenfield,composite_score,tier,is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (name) DO NOTHING",
                    (r.get("name"),r.get("account_type","BANK"),r.get("segment","COMMERCIAL"),r.get("country","Saudi Arabia"),r.get("website"),r.get("description"),bv(r.get("has_warm_contact",0)),bv(r.get("sama_pressure",0)),bv(r.get("is_greenfield",0)),r.get("composite_score",r.get("score",0)),r.get("tier","COLD"),bv(r.get("is_active",1))))
                n += 1
            except: pg.rollback()
        pg.commit(); print(f"  accounts:    {n}/{len(rows)}")

    if "contacts" in tables:
        pcur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pcur.execute("SELECT id,name FROM accounts")
        amap = {r["name"]:r["id"] for r in pcur.fetchall()}
        rows = [dict(r) for r in sq.execute("SELECT * FROM contacts").fetchall()]
        cur = pg.cursor(); n = 0
        for r in rows:
            aid = r.get("account_id") or amap.get(r.get("institution",""))
            try:
                cur.execute("INSERT INTO contacts (account_id,full_name,role,persona,seniority,is_ksa_national,relationship_type,institution,country,institution_type,segment,email,email_confidence,linkedin_url,whatsapp,phone,phone_status,key_signal,outreach_angle,product_fit,warmness,has_warm_relationship,background_notes,pitch_notes,connection_paths,priority_score,tier,current_touch,is_active,replied,do_not_contact,consent_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (full_name,institution) DO NOTHING",
                    (aid,r.get("full_name"),r.get("role","Unknown"),r.get("persona","OTHER"),r.get("seniority","VP"),bv(r.get("is_ksa_national",0)),r.get("relationship_type","TARGET"),r.get("institution",""),r.get("country","Saudi Arabia"),r.get("institution_type","Bank"),r.get("segment","COMMERCIAL"),r.get("email"),r.get("email_confidence"),r.get("linkedin_url"),r.get("whatsapp"),r.get("phone"),r.get("phone_status"),r.get("key_signal"),r.get("outreach_angle"),r.get("product_fit"),r.get("warmness","Cold"),bv(r.get("has_warm_relationship",0)),r.get("background_notes"),r.get("pitch_notes"),r.get("connection_paths"),r.get("priority_score",0),r.get("tier","COLD"),r.get("current_touch",0),bv(r.get("is_active",1)),bv(r.get("replied",0)),bv(r.get("do_not_contact",0)),r.get("consent_status","none")))
                n += 1
            except: pg.rollback()
        pg.commit(); print(f"  contacts:    {n}/{len(rows)}")

    for sq_name in ["signals"]:
        if sq_name not in tables: continue
        rows = [dict(r) for r in sq.execute(f"SELECT * FROM {sq_name}").fetchall()]
        cur = pg.cursor(); n = 0
        for r in rows:
            try:
                cur.execute("INSERT INTO signals (institution,signal_type,priority,headline,detail,source_url,source_name,score_impact,detected_at,account_id,is_read) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r.get("institution",""),r.get("signal_type",""),r.get("priority","P3"),r.get("headline",r.get("title","")),r.get("detail",r.get("summary","")),r.get("source_url",r.get("url","")),r.get("source_name",r.get("source","")),r.get("score_impact",0),r.get("detected_at",r.get("created_at")),r.get("account_id"),bv(r.get("is_read",0))))
                n += 1
            except: pg.rollback()
        pg.commit(); print(f"  signals:     {n}/{len(rows)}")

    for sq_name in ["draft_messages","drafts"]:
        if sq_name not in tables: continue
        rows = [dict(r) for r in sq.execute(f"SELECT * FROM {sq_name}").fetchall()]
        cur = pg.cursor(); n = 0
        for r in rows:
            st = r.get("status","DRAFT").upper()
            if st == "PENDING": st = "DRAFT"
            try:
                cur.execute("INSERT INTO drafts (contact_id,touch_number,touch_type,language,subject,body_en,body_ar,hook_used,status,source,generated_at,reviewed_at,sent_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r.get("contact_id"),r.get("touch_number",1),(r.get("touch_type",r.get("channel","EMAIL"))).upper(),r.get("language","EN"),r.get("subject"),r.get("body_en",r.get("body","")),r.get("body_ar"),r.get("hook_used",""),st,r.get("source","ai"),r.get("generated_at",r.get("created_at")),r.get("reviewed_at"),r.get("sent_at")))
                n += 1
            except: pg.rollback()
        pg.commit(); print(f"  drafts:      {n}/{len(rows)} (from {sq_name})")
        break

    for sq_name,pg_name,cols in [("touch_records","touch_log","contact_id,touch_type,language,status,subject,body,body_ar,signal_used,sent_at"),("touch_log","touch_log","contact_id,channel,subject,body,status,sent_at"),("news_items","news_items","category,institution,headline,summary,source_url,source_name,relevance_score,detected_at"),("templates","templates","name,channel,subject,body"),("audit_log","audit_log","action,details,timestamp"),("unsubscribes","unsubscribes","email,token")]:
        if sq_name not in tables: continue
        rows = [dict(r) for r in sq.execute(f"SELECT * FROM {sq_name}").fetchall()]
        cl = [c.strip() for c in cols.split(",")]
        cur = pg.cursor(); n = 0
        for r in rows:
            vals = [r.get(c) for c in cl]
            try:
                cur.execute(f"INSERT INTO {pg_name} ({cols}) VALUES ({','.join(['%s']*len(cl))})", vals)
                n += 1
            except: pg.rollback()
        pg.commit(); print(f"  {pg_name:14s} {n}/{len(rows)}")

    pcur = pg.cursor()
    pcur.execute("SELECT (SELECT COUNT(*) FROM accounts)+(SELECT COUNT(*) FROM contacts)+(SELECT COUNT(*) FROM signals)+(SELECT COUNT(*) FROM drafts)")
    print(f"\nTotal core rows in PG: {pcur.fetchone()[0]}")
    sq.close(); pg.close()

if __name__ == "__main__": run()
