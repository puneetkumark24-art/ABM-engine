"""
BRIP Dashboard — Banking Relationship Intelligence Platform
Connects to PostgreSQL brip database on localhost:5432
Run: python brip_app.py
Access: http://localhost:5001
"""
import os
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, jsonify, g
from datetime import datetime

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "brip-decimal-2026"

# ── Database Connection ──────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "brip",
    "user": "postgres",
    "password": os.environ.get("BRIP_DB_PASSWORD", "Puneet123@"),  # Change this!
}

def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(**DB_CONFIG)
        g.db.autocommit = True
    return g.db

def query(sql, params=None):
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        try:
            return cur.fetchall()
        except:
            return []

def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()

# ── Dashboard Routes ─────────────────────────────────────────

@app.route("/")
def index():
    """Main dashboard — platform overview"""
    stats = {
        "organizations": query_one("SELECT COUNT(*) AS c FROM organizations")["c"],
        "persons": query_one("SELECT COUNT(*) AS c FROM persons")["c"],
        "relationships_oo": query_one("SELECT COUNT(*) AS c FROM org_org_relationships")["c"],
        "relationships_pp": query_one("SELECT COUNT(*) AS c FROM person_person_relationships")["c"],
        "buying_committees": query_one("SELECT COUNT(*) AS c FROM buying_committee_members")["c"],
        "initiatives": query_one("SELECT COUNT(*) AS c FROM org_initiatives")["c"],
        "intel_observations": query_one("SELECT COUNT(*) AS c FROM org_intel_observations")["c"],
        "signals": query_one("SELECT COUNT(*) AS c FROM signals")["c"],
        "opportunities": query_one("SELECT COUNT(*) AS c FROM opportunities")["c"],
        "products": query_one("SELECT COUNT(*) AS c FROM products")["c"],
    }

    tier1_banks = query("""
        SELECT o.canonical_name, o.short_name, o.name_ar, o.decimal_priority,
               (SELECT COUNT(*) FROM persons p WHERE p.current_org_id = o.id) AS person_count,
               (SELECT COUNT(*) FROM org_initiatives i WHERE i.org_id = o.id) AS initiative_count,
               (SELECT COUNT(*) FROM org_intel_observations oi WHERE oi.org_id = o.id) AS intel_count
        FROM organizations o
        WHERE o.decimal_priority IN ('tier_1','tier_2')
          AND EXISTS (SELECT 1 FROM org_type_tags ot WHERE ot.org_id = o.id AND ot.type_tag IN ('commercial_bank','islamic_bank','digital_bank'))
        ORDER BY CASE o.decimal_priority WHEN 'tier_1' THEN 1 WHEN 'tier_2' THEN 2 ELSE 3 END, o.canonical_name
    """)

    return render_template("index.html", stats=stats, banks=tier1_banks)


@app.route("/bank/<short_name>")
def bank_detail(short_name):
    """Single bank intelligence view"""
    bank = query_one("""
        SELECT o.*, string_agg(DISTINCT ot.type_tag, ', ') AS types
        FROM organizations o
        LEFT JOIN org_type_tags ot ON ot.org_id = o.id
        WHERE o.short_name = %s
        GROUP BY o.id
    """, (short_name,))
    if not bank:
        return "Bank not found", 404

    bank_id = bank["id"]

    csuite = query("""
        SELECT p.full_name, p.current_title, p.seniority_level, p.primary_function,
               p.primary_email, p.is_decision_maker, p.is_influencer, p.is_connector
        FROM persons p
        WHERE p.current_org_id = %s AND p.seniority_level IN ('c_suite','svp_evp')
        ORDER BY CASE p.seniority_level WHEN 'c_suite' THEN 1 ELSE 2 END, p.current_title
    """, (bank_id,))

    champions = query("""
        SELECT p.full_name, p.current_title, p.seniority_level, p.primary_function, p.primary_email
        FROM persons p
        WHERE p.current_org_id = %s AND p.is_influencer = true AND p.seniority_level NOT IN ('c_suite','svp_evp')
        ORDER BY p.current_title
    """, (bank_id,))

    initiatives = query("""
        SELECT name, initiative_type, status, decimal_relevance, description, relevant_products
        FROM org_initiatives
        WHERE org_id = %s
        ORDER BY decimal_relevance DESC
    """, (bank_id,))

    intel = query("""
        SELECT category, title, body, confidence_score, observed_at, observation_type
        FROM org_intel_observations
        WHERE org_id = %s AND is_current = true
        ORDER BY confidence_score DESC
    """, (bank_id,))

    buying_committee = query("""
        SELECT p.full_name, p.current_title, bcm.role, bcm.influence_level,
               bcm.veto_power, bcm.budget_authority, bcm.decimal_sentiment, bcm.confidence
        FROM buying_committee_members bcm
        JOIN buying_committees bc ON bcm.committee_id = bc.id
        JOIN persons p ON bcm.person_id = p.id
        WHERE bc.org_id = %s
        ORDER BY bcm.influence_level DESC
    """, (bank_id,))

    connectors = query("""
        SELECT p.full_name, p.current_title, co.canonical_name AS connector_org,
               p.primary_email, p.mobile_phone,
               oor.relationship_type, oor.description AS rel_description
        FROM org_org_relationships oor
        JOIN organizations co ON (
            CASE WHEN oor.source_org_id = %s THEN oor.target_org_id ELSE oor.source_org_id END = co.id
        )
        JOIN persons p ON p.current_org_id = co.id AND p.is_connector = true
        WHERE (oor.source_org_id = %s OR oor.target_org_id = %s)
          AND co.id != %s
        ORDER BY co.canonical_name
    """, (bank_id, bank_id, bank_id, bank_id))

    tech_stack = query("""
        SELECT ts.technology_category, ts.product_name, ts.status, ts.contract_end,
               v.canonical_name AS vendor_name, ts.confidence_score
        FROM org_tech_stack ts
        LEFT JOIN organizations v ON ts.vendor_org_id = v.id
        WHERE ts.org_id = %s
        ORDER BY ts.technology_category
    """, (bank_id,))

    competitive = query("""
        SELECT ci.technology_category, ci.product_name, ci.relationship_status,
               ci.renewal_status, ci.decimal_advantage, ci.confidence,
               comp.canonical_name AS competitor_name
        FROM competitive_intelligence ci
        JOIN organizations comp ON ci.competitor_org_id = comp.id
        WHERE ci.target_org_id = %s
    """, (bank_id,))

    org_relationships = query("""
        SELECT 
            CASE WHEN oor.source_org_id = %s THEN t.canonical_name ELSE s.canonical_name END AS partner_name,
            oor.relationship_type, oor.status, oor.description
        FROM org_org_relationships oor
        JOIN organizations s ON oor.source_org_id = s.id
        JOIN organizations t ON oor.target_org_id = t.id
        WHERE oor.source_org_id = %s OR oor.target_org_id = %s
        ORDER BY oor.relationship_type
    """, (bank_id, bank_id, bank_id))

    return render_template("bank_detail.html",
        bank=bank, csuite=csuite, champions=champions, initiatives=initiatives,
        intel=intel, buying_committee=buying_committee, connectors=connectors,
        tech_stack=tech_stack, competitive=competitive, org_relationships=org_relationships
    )


@app.route("/persons")
def persons_list():
    """All persons directory"""
    org_filter = request.args.get("org", "")
    search = request.args.get("q", "")

    sql = """
        SELECT p.full_name, p.current_title, p.seniority_level, p.primary_function,
               p.primary_email, p.mobile_phone, p.is_decision_maker, p.is_connector,
               p.decimal_relationship_status, o.canonical_name AS org_name, o.short_name AS org_short
        FROM persons p
        LEFT JOIN organizations o ON p.current_org_id = o.id
        WHERE 1=1
    """
    params = []
    if org_filter:
        sql += " AND o.short_name = %s"
        params.append(org_filter)
    if search:
        sql += " AND (p.full_name ILIKE %s OR p.current_title ILIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])
    sql += " ORDER BY o.canonical_name, p.seniority_level, p.full_name"

    persons = query(sql, params)
    orgs = query("SELECT short_name, canonical_name FROM organizations ORDER BY canonical_name")
    return render_template("persons.html", persons=persons, orgs=orgs, org_filter=org_filter, search=search)


@app.route("/connectors")
def connectors_view():
    """All connector persons across ecosystem"""
    connectors = query("""
        SELECT p.full_name, p.current_title, o.canonical_name AS organization,
               p.primary_email, p.mobile_phone, p.decimal_relationship_status
        FROM persons p
        JOIN organizations o ON p.current_org_id = o.id
        WHERE p.is_connector = true
        ORDER BY o.canonical_name, p.full_name
    """)
    return render_template("connectors.html", connectors=connectors)


@app.route("/initiatives")
def initiatives_view():
    """All initiatives ranked by Decimal relevance"""
    initiatives = query("""
        SELECT i.name, i.initiative_type, i.status, i.decimal_relevance,
               i.description, i.relevant_products, o.canonical_name AS bank_name, o.short_name
        FROM org_initiatives i
        JOIN organizations o ON i.org_id = o.id
        ORDER BY i.decimal_relevance DESC
    """)
    return render_template("initiatives.html", initiatives=initiatives)


@app.route("/api/stats")
def api_stats():
    """JSON API for dashboard stats"""
    stats = query_one("""
        SELECT
            (SELECT COUNT(*) FROM organizations) AS orgs,
            (SELECT COUNT(*) FROM persons) AS persons,
            (SELECT COUNT(*) FROM org_org_relationships) AS org_rels,
            (SELECT COUNT(*) FROM buying_committee_members) AS committee_members,
            (SELECT COUNT(*) FROM org_initiatives) AS initiatives,
            (SELECT COUNT(*) FROM org_intel_observations) AS intel
    """)
    return jsonify(dict(stats))


# ── Run ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  BRIP Dashboard — Banking Relationship Intelligence")
    print("  http://localhost:5001")
    print("="*60 + "\n")
    app.run(host="127.0.0.1", port=5001, debug=True)
