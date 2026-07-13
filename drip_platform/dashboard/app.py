"""
DRIP Dashboard — Phase 5.

Reuses the visual design of brip_dashboard (found in Phase 1 discovery)
rewired to the actual drip schema/database instead of the never-built
"brip" Postgres database it originally pointed at. Same SQLAlchemy session
as the FastAPI layer (database.py) — single source of truth, no separate DB.

Bank pages show every contact loaded for that bank (paginated, filterable by
tier/seniority/Indian-origin/search) rather than a curated subset — the
earlier version only surfaced C-suite/Champions and silently hid everyone
else, which undercounted banks with 1000+ contacts.

Each contact can be edited in place (/person/<id>/edit) to log outreach —
connection sent/accepted, messaged, their response, and next step — since
the team has no CRM and this is meant to double as the outreach tracker.
There's no login system yet, so "updated by" is a free-text name field.

Run:  python dashboard/app.py        (defaults to http://127.0.0.1:5050)
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent.parent))
from flask import Flask, render_template, request, redirect, url_for, send_file, abort
from sqlalchemy import or_
import io
from database import SessionLocal, Base, engine, DATABASE_URL
import models
import scoring
from etl.import_incoming import (
    import_contacts_from_bytes, import_ecosystem_from_bytes, get_or_create_org, upsert_org_relationship,
)
from etl.document_reader import is_document_file, process_uploaded_document
from etl.signal_intel import classify_partnership, CLASSIFICATION_LABELS
from etl.signal_decay import stamp_signal_intelligence, is_decayed
from flow_map_pdf import render_flow_map_pdf

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB — dossiers can run large (scans, decks)

PAGE_SIZE = 100
URGENCY_TO_RELEVANCE = {"CRITICAL": 1.0, "HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}
TIER_TO_PRIORITY_KEY = {"Tier 1": "tier_1", "Tier 2": "tier_2", "Tier 3": "tier_3"}
# Org type_tags that mark an organization as ecosystem (vendor/subsidiary/partner) rather
# than a target bank — used to split the homepage into two searchable lists instead of
# mixing ITQAN/Tarabut/etc. in with the banks themselves.
ECOSYSTEM_TAGS = {"vendor", "subsidiary", "it_vendor", "fintech_vendor", "pos_merchant_vendor",
                   "bpo_vendor", "automation_vendor", "consulting", "alumni_network",
                   "card_network_partner", "open_banking_vendor", "digital_banking_platform", "fintech"}


def tier_to_priority_key(tier: str | None) -> str:
    return TIER_TO_PRIORITY_KEY.get(tier or "", "tier_3")


def signal_to_initiative(sig: "models.Signal", bank_name: str | None = None, org_id: str | None = None) -> dict:
    return {
        "id": sig.id,
        "name": (sig.title or sig.signal_type or "Signal")[:120],
        "initiative_type": sig.signal_type or "signal",
        "status": "actioned" if sig.is_actioned else "detected",
        "is_actioned": sig.is_actioned,
        "description": sig.summary or "",
        "urgency": sig.urgency,
        "source": sig.source,
        "url": sig.url,
        "decimal_relevance": URGENCY_TO_RELEVANCE.get(sig.urgency, 0.3),
        "relevant_products": [sig.product_match] if sig.product_match else [],
        "bank_name": bank_name,
        "org_id": sig.org_id or org_id,
        # SIG-TENDER (only populated when signal_type='rfp')
        "deadline": sig.deadline, "estimated_value": sig.estimated_value,
        "scope_description": sig.scope_description, "contact_person": sig.contact_person,
        "source_of_knowledge": sig.source_of_knowledge,
        # SIG-PARTNER (only populated when signal_type='partnership')
        "partner_classification": sig.partner_classification,
        "partner_classification_label": CLASSIFICATION_LABELS.get(sig.partner_classification),
        "partner_classification_matched_vendor": sig.partner_classification_matched_vendor,
        # Signal Pipeline P1 (EPIS-RCM-01/EPIS-HALF-01) — confidence + decay stamp.
        # is_decayed drives the visual de-emphasis the architecture doc calls for
        # on bank_detail.html/initiatives.html.
        "confidence_score": sig.confidence_score,
        "decay_category": sig.decay_category,
        "decay_expires_at": sig.decay_expires_at,
        "is_decayed": is_decayed(sig.decay_expires_at),
    }


SIGNAL_TYPES = ["leadership_change", "regulatory", "product_launch", "hiring", "funding",
                 "partnership", "rfp", "expansion", "earnings", "other"]
# CRITICAL sits above HIGH — per the ABM Business Logic Bible, RFPs/tenders (SIG-TENDER) and
# competitive-closure partnerships (SIG-PARTNER) are qualitatively more urgent than a routine
# HIGH signal: the buying decision is already being made, not just approaching.
SIGNAL_URGENCIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


OUTREACH_CHANNELS = ["linkedin", "email", "phone", "whatsapp"]
OUTREACH_CHANNEL_LABELS = {"linkedin": "LinkedIn", "email": "Email", "phone": "Phone", "whatsapp": "WhatsApp"}

# Suggested stages per channel — shown in an editable dropdown (datalist), never enforced.
# Sales teams describe progress in their own words, so typing anything else is always allowed.
OUTREACH_STAGE_SUGGESTIONS = {
    "linkedin": ["Connection request sent", "Connection accepted", "Message sent", "Replied", "Meeting booked", "No response"],
    "email": ["Email sent", "Opened", "Replied", "Auto-reply received", "Bounced", "No response"],
    "phone": ["Called — no answer", "Called — spoke briefly", "Full call completed", "Callback scheduled", "No response"],
    "whatsapp": ["Message sent", "Delivered", "Read", "Replied", "No response"],
}


def build_activity_summary(channels_by_key: dict) -> str:
    """Auto-generated one-line rollup across all 4 channels, so the contacts table always
    reflects what was actually logged instead of relying on someone to type it twice."""
    parts = []
    for ch in OUTREACH_CHANNELS:
        row = channels_by_key.get(ch)
        if row and row.stage:
            parts.append(f"{OUTREACH_CHANNEL_LABELS[ch]}: {row.stage}")
    return " · ".join(parts) if parts else "Not contacted yet"


def person_row(p, org_map: dict | None = None) -> dict:
    row = {
        "id": p.id, "full_name": p.full_name, "current_title": p.current_title,
        "priority_tier": p.priority_tier, "seniority_level": p.seniority_level,
        "is_indian_origin": p.is_indian_origin, "is_decision_maker": p.is_decision_maker,
        "is_connector": p.is_connector, "linkedin_url": p.linkedin_url,
        "primary_email": p.primary_email, "phone": p.phone,
        "last_activity_summary": p.last_activity_summary, "next_step": p.next_step,
    }
    if org_map is not None:
        row["org_id"] = p.current_org_id
        row["org_name"] = org_map.get(p.current_org_id)
    return row


def apply_filters(q, args):
    """Shared filter logic for both the bank-detail table and the global /persons table."""
    search = args.get("q", "").strip()
    tier_filter = args.get("tier", "").strip()
    seniority_filter = args.get("seniority", "").strip()
    indian_only = args.get("indian", "").strip() == "1"

    if search:
        q = q.filter(or_(models.Person.full_name.ilike(f"%{search}%"),
                          models.Person.current_title.ilike(f"%{search}%")))
    if tier_filter:
        q = q.filter(models.Person.priority_tier == tier_filter)
    if seniority_filter:
        q = q.filter(models.Person.seniority_level == seniority_filter)
    if indian_only:
        q = q.filter(models.Person.is_indian_origin == True)  # noqa: E712

    return q, {"search": search, "tier_filter": tier_filter,
               "seniority_filter": seniority_filter, "indian_only": indian_only}


def paginate(q, page: int):
    total_count = q.count()
    total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    items = q.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return items, total_count, total_pages, page


@app.route("/")
def index():
    db = SessionLocal()
    try:
        stats = {
            "organizations": db.query(models.Organization).count(),
            "persons": db.query(models.Person).count(),
            "relationships_oo": db.query(models.OrgRelationship).count(),
            "buying_committees": db.query(models.BuyingCommitteeMember).count(),
            "initiatives": db.query(models.Signal).count(),
            "intel_observations": 0,
            "products": db.query(models.Product).count(),
            "opportunities": db.query(models.Opportunity).count(),
        }

        search = request.args.get("q", "").strip()

        org_q = db.query(models.Organization).filter(models.Organization.is_active == True)  # noqa: E712
        if search:
            org_q = org_q.filter(models.Organization.canonical_name.ilike(f"%{search}%"))
        orgs = org_q.all()

        person_count_map, indian_count_map = defaultdict(int), defaultdict(int)
        for org_id, is_indian in db.query(models.Person.current_org_id, models.Person.is_indian_origin).filter(
                models.Person.current_org_id.isnot(None)).all():
            person_count_map[org_id] += 1
            if is_indian:
                indian_count_map[org_id] += 1
        signal_count_map = defaultdict(int)
        for org_id, _ in db.query(models.Signal.org_id, models.Signal.id).filter(
                models.Signal.org_id.isnot(None)).all():
            signal_count_map[org_id] += 1
        connected_bank_count_map = defaultdict(int)
        for from_org_id, _ in db.query(models.OrgRelationship.from_org_id, models.OrgRelationship.id).all():
            connected_bank_count_map[from_org_id] += 1

        accounts = {a.org_id: a for a in db.query(models.AccountIntelligence).all()}

        banks, ecosystem_orgs = [], []
        for o in orgs:
            org_tags = [t.type_tag for t in o.type_tags]
            acc = accounts.get(o.id)
            if any(t in ECOSYSTEM_TAGS for t in org_tags):
                ecosystem_orgs.append({
                    "id": o.id, "canonical_name": o.canonical_name, "type_tags": org_tags,
                    "contact_count": person_count_map.get(o.id, 0),
                    "connected_bank_count": connected_bank_count_map.get(o.id, 0),
                })
            else:
                banks.append({
                    "id": o.id, "canonical_name": o.canonical_name, "name_ar": o.name_ar,
                    "country": o.country,
                    "decimal_priority": tier_to_priority_key(acc.tier if acc else None),
                    "person_count": person_count_map.get(o.id, 0),
                    "indian_count": indian_count_map.get(o.id, 0),
                    "initiative_count": signal_count_map.get(o.id, 0),
                    "intel_count": 0,
                })
        banks.sort(key=lambda b: (b["decimal_priority"] not in ("tier_1", "tier_2"), -b["person_count"]))
        ecosystem_orgs.sort(key=lambda e: (-e["connected_bank_count"], e["canonical_name"]))

        return render_template("index.html", stats=stats, banks=banks,
                                ecosystem_orgs=ecosystem_orgs, search=search)
    finally:
        db.close()


ORG_TYPE_TAG_OPTIONS = [
    ("commercial_bank", "Commercial Bank"), ("islamic_bank", "Islamic Bank"),
    ("digital_bank", "Digital Bank"), ("bnpl", "BNPL"),
    ("vendor", "Vendor"), ("subsidiary", "Subsidiary"),
    ("fintech", "Fintech"), ("consulting", "Consulting"),
    ("regulator", "Regulator"), ("association", "Association"),
]


@app.route("/organizations/new", methods=["GET", "POST"])
def organization_new():
    """Manually add a bank (or vendor/subsidiary/etc.) that isn't on the dashboard yet —
    the counterpart to the existing bulk ETL loaders, for the one-off case of adding a
    single new account. Created with verification_status='unverified' since nothing here
    is looked up automatically; it's exactly what's typed into the form."""
    db = SessionLocal()
    try:
        if request.method == "POST":
            name = request.form.get("canonical_name", "").strip()
            if not name:
                return render_template("org_new.html", type_tag_options=ORG_TYPE_TAG_OPTIONS,
                                        error="Bank / organization name is required.", form=request.form)

            existing = db.query(models.Organization).filter(
                models.Organization.canonical_name.ilike(name)).first()
            if existing:
                # Already on the dashboard under this name — go straight there instead of
                # hitting the canonical_name unique constraint with a confusing 500 error.
                return redirect(url_for("bank_detail", org_id=existing.id))

            org = models.Organization(
                canonical_name=name,
                name_ar=request.form.get("name_ar", "").strip() or None,
                country=request.form.get("country", "").strip() or "Saudi Arabia",
                website=request.form.get("website", "").strip() or None,
                source="Manually added via dashboard",
                verification_status="unverified",
            )
            db.add(org)
            db.flush()

            selected_tags = request.form.getlist("type_tags") or ["commercial_bank"]
            for tag in selected_tags:
                db.add(models.OrgTypeTag(org_id=org.id, type_tag=tag))

            db.commit()
            return redirect(url_for("bank_detail", org_id=org.id))

        return render_template("org_new.html", type_tag_options=ORG_TYPE_TAG_OPTIONS, error=None, form={})
    finally:
        db.close()


@app.route("/bank/<org_id>")
def bank_detail(org_id):
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404
        acc = db.get(models.AccountIntelligence, org_id)
        type_tags = [t.type_tag for t in org.type_tags]

        base_q = db.query(models.Person).filter(models.Person.current_org_id == org_id)
        total_all = base_q.count()

        tier_counts = {t: base_q.filter(models.Person.priority_tier == t).count()
                       for t in ("Tier 1", "Tier 2", "Tier 3")}
        indian_count = base_q.filter(models.Person.is_indian_origin == True).count()  # noqa: E712
        csuite_count = base_q.filter(models.Person.seniority_level == "c_suite").count()
        champions_count = base_q.filter(models.Person.is_influencer == True,  # noqa: E712
                                         models.Person.seniority_level != "c_suite").count()

        filtered_q, filt = apply_filters(base_q, request.args)
        filtered_q = filtered_q.order_by(models.Person.priority_score.desc().nullslast(),
                                          models.Person.full_name)
        page = int(request.args.get("page", 1) or 1)
        people, total_count, total_pages, page = paginate(filtered_q, page)

        bank = {
            "canonical_name": org.canonical_name, "name_ar": org.name_ar,
            "types": ", ".join(type_tags), "headquarters_city": "", "headquarters_country": org.country,
            "decimal_priority": tier_to_priority_key(acc.tier if acc else None),
            "website": org.website, "total_contacts": total_all,
        }

        signals = (db.query(models.Signal).filter(models.Signal.org_id == org_id)
                   .order_by(models.Signal.created_at.desc()).limit(30).all())
        initiatives = [signal_to_initiative(s) for s in signals]

        ecosystem_vendors, connected_banks = build_ecosystem_lists(db, org_id)

        org_person_ids = [pid for (pid,) in db.query(models.Person.id)
                          .filter(models.Person.current_org_id == org_id).all()]
        connector_chains = []
        if org_person_ids:
            chains = db.query(models.PersonRelationship).filter(
                models.PersonRelationship.to_person_id.in_(org_person_ids),
                models.PersonRelationship.relationship_type == "introduces").all()
            for ch in chains:
                from_p = db.get(models.Person, ch.from_person_id) if ch.from_person_id else None
                to_p = db.get(models.Person, ch.to_person_id)
                connector_chains.append({
                    "from_name": from_p.full_name if from_p else ch.from_name,
                    "from_org": (db.get(models.Organization, from_p.current_org_id).canonical_name
                                 if from_p and from_p.current_org_id else None),
                    "to_name": to_p.full_name if to_p else "",
                    "context": ch.context,
                })

        tech_fields = ["core_banking", "crm", "los", "lms", "collections", "treasury", "payments",
                       "risk", "fraud", "aml", "kyc", "cloud", "api_gateway"]
        tech_stack = [{"name": f, "value": getattr(org, f)} for f in tech_fields if getattr(org, f)]

        # Document Intelligence: PDFs/images uploaded for this bank, read immediately on upload
        # (etl/document_reader.py) — shown here with their rule-based summary and detected
        # organization mentions, each one click away from becoming a real connection-map entry.
        doc_uploads = (db.query(models.DocumentUpload)
                       .filter(models.DocumentUpload.org_id == org_id,
                               models.DocumentUpload.status.in_(["processed", "failed"]))
                       .order_by(models.DocumentUpload.created_at.desc()).all())
        already_connected = {v["canonical_name"].strip().lower() for v in ecosystem_vendors}
        document_intel = []
        for u in doc_uploads:
            if is_document_file(u.filename) is None:
                continue
            entities = [
                {**e, "is_connected": e["name"].strip().lower() in already_connected}
                for e in (u.detected_entities or [])
            ]
            document_intel.append({
                "id": u.id, "filename": u.filename, "status": u.status,
                "summary": u.extracted_summary, "processing_notes": u.processing_notes,
                "entities": entities, "created_at": u.created_at,
            })

        base_params = {k: v for k, v in [("q", filt["search"]), ("tier", filt["tier_filter"]),
                                          ("seniority", filt["seniority_filter"]),
                                          ("indian", "1" if filt["indian_only"] else "")] if v}

        return render_template(
            "bank_detail.html", bank=bank,
            tier_counts=tier_counts, indian_count=indian_count,
            csuite_count=csuite_count, champions_count=champions_count,
            persons=[person_row(p) for p in people], show_org=False,
            search=filt["search"], tier_filter=filt["tier_filter"],
            seniority_filter=filt["seniority_filter"], indian_only=filt["indian_only"],
            page=page, total_pages=total_pages, total_count=total_count,
            base_url_params=urlencode(base_params),
            initiatives=initiatives, tech_stack=tech_stack,
            ecosystem_vendors=ecosystem_vendors, connected_banks=connected_banks,
            connector_chains=connector_chains, acc=acc, document_intel=document_intel,
        )
    finally:
        db.close()


@app.route("/bank/<org_id>/flow")
def bank_flow(org_id):
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404
        flow_data = build_flow_map_data(db, org_id)
        return render_template("bank_flow.html", org=org, **flow_data)
    finally:
        db.close()


@app.route("/bank/<org_id>/flow/pdf")
def bank_flow_pdf(org_id):
    """Same data as /flow, rendered as a downloadable landscape PDF styled to match the
    BD dossier connection-flow diagrams (dark navy header, four colored columns, tier
    badges) — built with reportlab (already a project dependency, pure-Python) rather
    than an HTML-to-PDF engine, specifically to avoid a repeat of the Tesseract-style
    native-dependency install headache on Windows."""
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404
        flow_data = build_flow_map_data(db, org_id)
        pdf_bytes = render_flow_map_pdf(org, flow_data)
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in org.canonical_name).strip("_")
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                          as_attachment=True, download_name=f"{safe_name}_Connection_Flow_Map.pdf")
    finally:
        db.close()


def build_flow_map_data(db, org_id):
    """Builds everything the ecosystem connection-flow map needs — on-screen and PDF
    alike, both call this so they can never drift apart. Four columns:
      - Decimal: this bank's actual scored product fits (falls back to Decimal's active
        product catalog if nothing's been scored yet, so the column is never empty)
      - External Connectors: contacts at connected orgs with no assigned flow role
      - Subsidiary Champions: champions grouped into a box per subsidiary org, each
        box carrying a star rating from that subsidiary's OrgRelationship strength
      - C-Suite Targets: this bank's own decision-makers + c-suite contacts, merged
        into one list and ranked by bd_priority (matches the reference dossier layout,
        which shows one "C-Suite Targets" column, not two separate ones)
    Plus a stats-based summary line — counts pulled live from what's actually loaded,
    not hand-written, so it works for any bank and stays current as data changes."""
    org = db.get(models.Organization, org_id)
    ecosystem_vendors, _connected_banks = build_ecosystem_lists(db, org_id)
    related_org_ids = [v["org_id"] for v in ecosystem_vendors]

    connectors = db.query(models.Person).filter(
        models.Person.current_org_id.in_(related_org_ids) if related_org_ids else False,
        models.Person.bd_flow_column.is_(None)).all() if related_org_ids else []

    champion_org_ids = related_org_ids + [org_id]
    champions = db.query(models.Person).filter(
        models.Person.current_org_id.in_(champion_org_ids),
        models.Person.bd_flow_column == "champion").all()

    decision_makers = db.query(models.Person).filter(
        models.Person.current_org_id == org_id,
        models.Person.bd_flow_column == "decision_maker").all()

    c_suite_raw = db.query(models.Person).filter(
        models.Person.current_org_id == org_id,
        models.Person.bd_flow_column == "c_suite").all()

    priority_rank = {"Final Authority": 0, "P1": 1, "Critical": 1.5, "P2": 2, "P3": 3}
    c_suite_combined = c_suite_raw + decision_makers
    c_suite_combined.sort(key=lambda p: priority_rank.get(p.bd_priority, 9))

    def org_name(oid):
        o = db.get(models.Organization, oid)
        return o.canonical_name if o else None

    def card(p):
        return {"id": p.id, "full_name": p.full_name, "current_title": p.current_title,
                "bd_priority": p.bd_priority, "org_name": org_name(p.current_org_id),
                "phone": p.phone, "primary_email": p.primary_email,
                "email_confidence": p.email_confidence}

    # Subsidiary Champions — grouped by the org they sit at rather than a flat person
    # list, so the map reads the same way the reference dossier does: one box per
    # subsidiary (with a star rating from that OrgRelationship's strength), names inside.
    strength_stars = {"Strong": "★★★", "Medium": "★★", "Weak": "★"}
    subsidiary_orgs = {v["org_id"]: v for v in ecosystem_vendors if v["relationship_type"] == "subsidiary"}
    subsidiary_groups = []
    grouped_person_ids = set()
    for oid, v in subsidiary_orgs.items():
        members = [card(p) for p in champions if p.current_org_id == oid]
        grouped_person_ids.update(p.id for p in champions if p.current_org_id == oid)
        subsidiary_groups.append({
            "org_id": oid, "canonical_name": v["canonical_name"],
            "stars": strength_stars.get(v["strength"], ""), "members": members,
        })
    # Champions at the bank itself or a non-subsidiary connected org (e.g. a partner) don't
    # have a subsidiary box to sit in — keep them as their own single-person group rather
    # than silently dropping them off the map.
    for p in champions:
        if p.id not in grouped_person_ids:
            subsidiary_groups.append({
                "org_id": p.current_org_id, "canonical_name": org_name(p.current_org_id) or "",
                "stars": "", "members": [card(p)],
            })
    subsidiary_groups.sort(key=lambda g: -len(g["members"]))

    # Decimal column — this bank's actual scored product fits, so it's real per-bank
    # content instead of boilerplate. Falls back to the active product catalog if this
    # bank hasn't had a fit scored yet.
    fits = db.query(models.ProductFit).filter(models.ProductFit.org_id == org_id).order_by(
        models.ProductFit.fit_score.desc()).all()
    decimal_items = []
    for f in fits:
        product = db.get(models.Product, f.product_id)
        if product:
            decimal_items.append(product.name + (f" — {f.pitch_angle}" if f.pitch_angle else ""))
    if not decimal_items:
        decimal_items = [p.name for p in db.query(models.Product).limit(6).all()]

    connectors_cards = [card(p) for p in connectors]
    c_suite_cards = [card(p) for p in c_suite_combined]

    has_flow_data = bool(connectors or champions or decision_makers or c_suite_raw)

    # Connector lines between the cards actually shown in this view — only edges where
    # both ends are in the current columns get drawn (this is what makes the flow map
    # show WHO introduces WHO, not just disconnected lists of names).
    all_ids = {p.id for p in connectors + champions + decision_makers + c_suite_raw}
    edges = []
    if all_ids:
        rels = db.query(models.PersonRelationship).filter(
            models.PersonRelationship.relationship_type == "introduces",
            models.PersonRelationship.from_person_id.in_(all_ids),
            models.PersonRelationship.to_person_id.in_(all_ids)).all()
        edges = [{"from": r.from_person_id, "to": r.to_person_id, "context": r.context or ""}
                 for r in rels]

    account = db.get(models.AccountIntelligence, org_id)
    summary_bits = [
        f"{len(connectors_cards)} connector{'s' if len(connectors_cards) != 1 else ''}",
        f"{len(champions)} champion{'s' if len(champions) != 1 else ''}",
        f"{len(c_suite_cards)} C-suite target{'s' if len(c_suite_cards) != 1 else ''}",
        f"{len(subsidiary_orgs)} subsidiar{'y' if len(subsidiary_orgs) == 1 else 'ies'}",
        f"{len(ecosystem_vendors)} total ecosystem connection{'s' if len(ecosystem_vendors) != 1 else ''}",
    ]
    if account and account.tier:
        tier_bit = account.tier + (f" · {account.priority}" if account.priority else "")
        summary_bits.append(tier_bit)
    summary_line = " · ".join(summary_bits)

    return {
        "connectors": connectors_cards,
        "subsidiary_groups": subsidiary_groups,
        "c_suite": c_suite_cards,
        "decimal_items": decimal_items,
        "has_flow_data": has_flow_data,
        "edges": edges,
        "summary_line": summary_line,
    }


RELATIONSHIP_GROUP_ORDER = ["regulator_of", "parent", "subsidiary", "vendor", "partner", "serves",
                            "alumni_network", "competitor"]
RELATIONSHIP_GROUP_LABELS = {
    "regulator_of": "Regulators / Authorities", "parent": "Parent Organization",
    "subsidiary": "Subsidiaries", "vendor": "Vendors", "partner": "Partners",
    "serves": "Serves", "alumni_network": "Alumni Networks", "competitor": "Competitors",
}


@app.route("/bank/<org_id>/connection-map")
def bank_connection_map(org_id):
    """Ecosystem connection map — separate from the person-based /flow page (which needs
    bd_flow_column data imported from a BD dossier and is mostly empty outside SNB). This
    one is driven purely by OrgRelationship rows (vendor/subsidiary/regulator/partner links),
    which every bank now has a path to populate via the manual 'Add vendor' form or the
    ecosystem CSV/Excel import — so it works for any bank, not just the ones with a
    hand-built dossier.

    The point isn't just to draw a picture — it's to surface the actual entry paths: any
    connected org where Decimal already has contacts is a potential way in, and any connected
    org that ALSO serves other target banks (cross_connections) is a lever that opens more
    than one door at once."""
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404

        ecosystem_vendors, _connected_banks = build_ecosystem_lists(db, org_id)

        groups = defaultdict(list)
        for v in ecosystem_vendors:
            groups[v["relationship_type"] or "vendor"].append(v)

        ordered_groups = []
        seen = set()
        for key in RELATIONSHIP_GROUP_ORDER:
            if key in groups:
                ordered_groups.append((key, RELATIONSHIP_GROUP_LABELS.get(key, key.replace("_", " ").title()),
                                        groups[key]))
                seen.add(key)
        for key, items in groups.items():
            if key not in seen:
                ordered_groups.append((key, RELATIONSHIP_GROUP_LABELS.get(key, key.replace("_", " ").title()),
                                        items))

        # Cross-bank reach: for each connected org, which OTHER banks/orgs does IT also
        # connect to? A shared vendor that also serves two other target banks means one
        # relationship there is a lever on three accounts, not one.
        cross_connections = {}
        for v in ecosystem_vendors:
            _, other_side = build_ecosystem_lists(db, v["org_id"])
            others = [b for b in other_side if b["org_id"] != org_id]
            if others:
                cross_connections[v["org_id"]] = others

        entry_points = [v for v in ecosystem_vendors if v["contact_count"] > 0]
        cross_reach_count = len(cross_connections)

        # Candidates detected in uploaded PDFs/images (etl/document_reader.py) that aren't
        # already a confirmed connection — shown as a dashed "not yet confirmed" section so a
        # document upload shows up in the map right away, one click away from being real.
        already_connected = {v["canonical_name"].strip().lower() for v in ecosystem_vendors}
        doc_uploads = db.query(models.DocumentUpload).filter(
            models.DocumentUpload.org_id == org_id, models.DocumentUpload.status == "processed").all()
        candidate_map: dict[str, dict] = {}
        for u in doc_uploads:
            for e in (u.detected_entities or []):
                norm = e["name"].strip().lower()
                if norm in already_connected:
                    continue
                existing = candidate_map.get(norm)
                if not existing or e["count"] > existing["count"]:
                    candidate_map[norm] = {**e, "source_filename": u.filename}
        document_candidates = sorted(candidate_map.values(), key=lambda e: -e["count"])[:20]

        return render_template(
            "bank_connection_map.html", org=org, ecosystem_vendors=ecosystem_vendors,
            ordered_groups=ordered_groups, cross_connections=cross_connections,
            entry_points=entry_points, cross_reach_count=cross_reach_count,
            document_candidates=document_candidates,
        )
    finally:
        db.close()


def build_ecosystem_lists(db, org_id):
    """Returns (ecosystem_vendors, connected_banks):
    - ecosystem_vendors: orgs that connect TO org_id as a vendor/subsidiary/partner
      (org_id is the bank being served) — shown on a bank's page.
    - connected_banks: orgs that org_id itself connects TO as a vendor/subsidiary/partner
      (org_id is the vendor) — shown on a vendor's own page, e.g. "Tarabut is also
      connected to Riyad Bank, Al Rajhi Bank..." — the whole point of not burying a
      vendor's cross-bank reach inside just one bank's page.
    """
    rels_in = db.query(models.OrgRelationship).filter(models.OrgRelationship.to_org_id == org_id).all()
    rels_out = db.query(models.OrgRelationship).filter(models.OrgRelationship.from_org_id == org_id).all()

    ecosystem_vendors = []
    for r in rels_in:
        other = db.get(models.Organization, r.from_org_id)
        if not other:
            continue
        contact_count = db.query(models.Person).filter(models.Person.current_org_id == other.id).count()
        ecosystem_vendors.append({
            "rel_id": r.id, "org_id": other.id, "canonical_name": other.canonical_name,
            "type_tags": [t.type_tag for t in other.type_tags],
            "relationship_type": r.relationship_type, "strength": r.strength,
            "confidence": r.confidence, "context": r.context, "contact_count": contact_count,
        })

    connected_banks = []
    for r in rels_out:
        other = db.get(models.Organization, r.to_org_id)
        if not other:
            continue
        connected_banks.append({
            "org_id": other.id, "canonical_name": other.canonical_name,
            "relationship_type": r.relationship_type, "strength": r.strength,
            "confidence": r.confidence, "context": r.context,
        })

    return ecosystem_vendors, connected_banks


def delete_organization_cascade(db, org_id: str):
    """Fully removes a bank/org and everything that points at it. FKs here aren't set up
    with ON DELETE CASCADE at the DB level (so this works identically on SQLite and
    Postgres), so every dependent table is cleaned up by hand, in dependency order,
    inside one transaction. Uploaded documents are NOT deleted — they're just unlinked
    (org_id set to null) so the underlying files aren't lost if this was a mistake.
    Other organizations that list this one as their parent_org_id are detached rather
    than deleted."""
    person_ids = [pid for (pid,) in db.query(models.Person.id)
                  .filter(models.Person.current_org_id == org_id).all()]

    if person_ids:
        db.query(models.OutreachChannel).filter(models.OutreachChannel.person_id.in_(person_ids)).delete(
            synchronize_session=False)
        db.query(models.PersonRelationship).filter(
            or_(models.PersonRelationship.from_person_id.in_(person_ids),
                models.PersonRelationship.to_person_id.in_(person_ids))).delete(synchronize_session=False)
        db.query(models.BuyingCommitteeMember).filter(
            models.BuyingCommitteeMember.person_id.in_(person_ids)).delete(synchronize_session=False)

    db.query(models.BuyingCommitteeMember).filter(models.BuyingCommitteeMember.org_id == org_id).delete(
        synchronize_session=False)
    db.query(models.Opportunity).filter(models.Opportunity.org_id == org_id).delete(synchronize_session=False)
    db.query(models.ProductFit).filter(models.ProductFit.org_id == org_id).delete(synchronize_session=False)
    db.query(models.AccountScore).filter(models.AccountScore.org_id == org_id).delete(synchronize_session=False)
    db.query(models.Signal).filter(models.Signal.org_id == org_id).delete(synchronize_session=False)
    db.query(models.VendorIntelligence).filter(models.VendorIntelligence.org_id == org_id).delete(
        synchronize_session=False)

    if person_ids:
        db.query(models.Person).filter(models.Person.current_org_id == org_id).delete(synchronize_session=False)

    db.query(models.DocumentUpload).filter(models.DocumentUpload.org_id == org_id).update(
        {"org_id": None}, synchronize_session=False)

    db.query(models.OrgRelationship).filter(
        or_(models.OrgRelationship.from_org_id == org_id, models.OrgRelationship.to_org_id == org_id)
    ).delete(synchronize_session=False)

    db.query(models.Organization).filter(models.Organization.parent_org_id == org_id).update(
        {"parent_org_id": None}, synchronize_session=False)

    org = db.get(models.Organization, org_id)
    if org:
        db.delete(org)  # cascades to OrgTypeTag + AccountIntelligence via relationship cascade
    db.commit()


@app.route("/bank/<org_id>/delete", methods=["GET", "POST"])
def bank_delete(org_id):
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404

        if request.method == "POST":
            delete_organization_cascade(db, org_id)
            return redirect(url_for("index"))

        counts = {
            "contacts": db.query(models.Person).filter(models.Person.current_org_id == org_id).count(),
            "signals": db.query(models.Signal).filter(models.Signal.org_id == org_id).count(),
            "relationships": db.query(models.OrgRelationship).filter(
                or_(models.OrgRelationship.from_org_id == org_id,
                    models.OrgRelationship.to_org_id == org_id)).count(),
            "uploads": db.query(models.DocumentUpload).filter(models.DocumentUpload.org_id == org_id).count(),
        }
        return render_template("confirm_delete.html",
                                title=f"Delete {org.canonical_name}?",
                                message=("This permanently removes the bank/organization and every contact, "
                                         "signal, and vendor/subsidiary connection tied to it. This can't be undone."),
                                extra_details=[
                                    ("Contacts", counts["contacts"]),
                                    ("Signals / initiatives", counts["signals"]),
                                    ("Vendor / subsidiary connections", counts["relationships"]),
                                    ("Uploaded documents (kept, just unlinked)", counts["uploads"]),
                                ],
                                confirm_url=url_for("bank_delete", org_id=org_id),
                                confirm_label="Yes, delete this bank",
                                cancel_url=url_for("bank_detail", org_id=org_id))
    finally:
        db.close()


VENDOR_RELATIONSHIP_TYPES = ["vendor", "subsidiary", "partner", "serves", "regulator_of", "competitor",
                             "parent", "alumni_network"]
VENDOR_STRENGTHS = ["Strong", "Medium", "Weak"]


@app.route("/bank/<org_id>/vendor/new", methods=["GET", "POST"])
def vendor_new(org_id):
    """Add a vendor/subsidiary connection to a bank — either linking an org that's already
    on the dashboard, or typing a new name (created on the spot, same as the standalone
    'Add bank' flow but tagged as vendor/subsidiary/etc. by default instead of a bank).
    Reuses upsert_org_relationship so adding the same vendor twice updates the one
    relationship row instead of creating a duplicate."""
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404

        if request.method == "POST":
            existing_org_id = request.form.get("existing_org_id", "").strip() or None
            vendor_name = request.form.get("vendor_name", "").strip() or None
            error = None

            if existing_org_id:
                vendor_org = db.get(models.Organization, existing_org_id)
                if not vendor_org:
                    error = "That organization couldn't be found."
            elif vendor_name:
                selected_tags = request.form.getlist("type_tags") or ["vendor"]
                vendor_org, _created = get_or_create_org(db, vendor_name, default_type_tag=selected_tags[0])
                existing_tags = {t.type_tag for t in vendor_org.type_tags}
                for tag in selected_tags[1:]:
                    if tag not in existing_tags:
                        db.add(models.OrgTypeTag(org_id=vendor_org.id, type_tag=tag))
            else:
                error = "Pick an existing organization or type a new vendor/subsidiary name."

            if error:
                orgs = db.query(models.Organization).filter(models.Organization.id != org_id).order_by(
                    models.Organization.canonical_name).all()
                return render_template("vendor_edit.html", org=org, rel=None, vendor_org=None, orgs=orgs,
                                       relationship_types=VENDOR_RELATIONSHIP_TYPES, strengths=VENDOR_STRENGTHS,
                                       type_tag_options=ORG_TYPE_TAG_OPTIONS, error=error, form=request.form)

            confidence_raw = request.form.get("confidence", "50").strip()
            try:
                confidence = float(confidence_raw) / 100
            except ValueError:
                confidence = 0.5

            upsert_org_relationship(
                db, from_org_id=vendor_org.id, to_org_id=org_id,
                relationship_type=request.form.get("relationship_type", "vendor").strip() or "vendor",
                strength=request.form.get("strength", "Weak").strip() or "Weak",
                confidence=confidence, context=request.form.get("context", "").strip() or None,
                source="Manually added via dashboard",
            )
            db.commit()
            return redirect(url_for("bank_detail", org_id=org_id))

        orgs = db.query(models.Organization).filter(models.Organization.id != org_id).order_by(
            models.Organization.canonical_name).all()
        # Quick-add links (from the Document Intelligence card / connection-map candidates) land
        # here with ?vendor_name=...&relationship_type=... to prefill the form — one click from
        # "detected in a document" to "confirmed connection", without retyping the name.
        prefill_form = {}
        if request.args.get("vendor_name"):
            prefill_form["vendor_name"] = request.args.get("vendor_name")
        if request.args.get("relationship_type"):
            prefill_form["relationship_type"] = request.args.get("relationship_type")
        if request.args.get("context"):
            prefill_form["context"] = request.args.get("context")
        return render_template("vendor_edit.html", org=org, rel=None, vendor_org=None, orgs=orgs,
                               relationship_types=VENDOR_RELATIONSHIP_TYPES, strengths=VENDOR_STRENGTHS,
                               type_tag_options=ORG_TYPE_TAG_OPTIONS, error=None, form=prefill_form)
    finally:
        db.close()


@app.route("/bank/<org_id>/vendor/<rel_id>/edit", methods=["GET", "POST"])
def vendor_edit(org_id, rel_id):
    """Edit an existing vendor/subsidiary relationship's metadata (relationship type,
    strength, confidence, context). To connect a different organization instead, delete
    this connection and add a new one — this only edits the relationship itself."""
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        rel = db.get(models.OrgRelationship, rel_id)
        if not org or not rel or rel.to_org_id != org_id:
            return "Not found", 404
        vendor_org = db.get(models.Organization, rel.from_org_id)

        if request.method == "POST":
            confidence_raw = request.form.get("confidence", "50").strip()
            try:
                confidence = float(confidence_raw) / 100
            except ValueError:
                confidence = rel.confidence

            rel.relationship_type = request.form.get("relationship_type", "vendor").strip() or "vendor"
            rel.strength = request.form.get("strength", "Weak").strip() or "Weak"
            rel.confidence = confidence
            rel.context = request.form.get("context", "").strip() or None
            db.commit()
            return redirect(url_for("bank_detail", org_id=org_id))

        form = {"relationship_type": rel.relationship_type, "strength": rel.strength,
                "confidence": int(round((rel.confidence or 0.5) * 100)), "context": rel.context or ""}
        return render_template("vendor_edit.html", org=org, rel=rel, vendor_org=vendor_org, orgs=[],
                               relationship_types=VENDOR_RELATIONSHIP_TYPES, strengths=VENDOR_STRENGTHS,
                               type_tag_options=ORG_TYPE_TAG_OPTIONS, error=None, form=form)
    finally:
        db.close()


@app.route("/bank/<org_id>/vendor/<rel_id>/delete", methods=["POST"])
def vendor_delete(org_id, rel_id):
    """Deletes only the relationship row — the vendor/subsidiary organization itself is
    left alone, since it may be connected to other banks too."""
    db = SessionLocal()
    try:
        rel = db.get(models.OrgRelationship, rel_id)
        if rel and rel.to_org_id == org_id:
            db.delete(rel)
            db.commit()
        return redirect(url_for("bank_detail", org_id=org_id))
    finally:
        db.close()


PERSON_TIERS = ["Tier 1", "Tier 2", "Tier 3"]
PERSON_SENIORITIES = ["c_suite", "svp_evp", "director", "manager"]


@app.route("/bank/<org_id>/person/new", methods=["GET", "POST"])
def person_new(org_id):
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            if not full_name:
                return render_template("person_new.html", org=org, tiers=PERSON_TIERS,
                                       seniorities=PERSON_SENIORITIES,
                                       error="Name is required.", form=request.form)

            person = models.Person(
                full_name=full_name, current_org_id=org_id,
                current_title=request.form.get("current_title", "").strip() or None,
                primary_email=request.form.get("primary_email", "").strip() or None,
                phone=request.form.get("phone", "").strip() or None,
                linkedin_url=request.form.get("linkedin_url", "").strip() or None,
                priority_tier=request.form.get("priority_tier", "").strip() or None,
                seniority_level=request.form.get("seniority_level", "").strip() or None,
                persona=request.form.get("persona", "").strip() or None,
                country=request.form.get("country", "").strip() or None,
                background_notes=request.form.get("background_notes", "").strip() or None,
                is_indian_origin=request.form.get("is_indian_origin") == "on",
                is_decision_maker=request.form.get("is_decision_maker") == "on",
                is_connector=request.form.get("is_connector") == "on",
                data_source="Manually added via dashboard",
            )
            db.add(person)
            db.commit()
            return redirect(url_for("bank_detail", org_id=org_id))

        return render_template("person_new.html", org=org, tiers=PERSON_TIERS,
                               seniorities=PERSON_SENIORITIES, error=None, form={})
    finally:
        db.close()


@app.route("/person/<person_id>/delete", methods=["GET", "POST"])
def person_delete(person_id):
    db = SessionLocal()
    try:
        p = db.get(models.Person, person_id)
        if not p:
            return "Person not found", 404
        next_url = request.values.get("next") or url_for("persons_page")

        if request.method == "POST":
            db.query(models.OutreachChannel).filter(models.OutreachChannel.person_id == person_id).delete(
                synchronize_session=False)
            db.query(models.PersonRelationship).filter(
                or_(models.PersonRelationship.from_person_id == person_id,
                    models.PersonRelationship.to_person_id == person_id)).delete(synchronize_session=False)
            db.query(models.BuyingCommitteeMember).filter(
                models.BuyingCommitteeMember.person_id == person_id).delete(synchronize_session=False)
            db.delete(p)
            db.commit()
            return redirect(next_url)

        org = db.get(models.Organization, p.current_org_id) if p.current_org_id else None
        return render_template("confirm_delete.html",
                                title=f"Delete {p.full_name}?",
                                message="This permanently removes this contact and their outreach history.",
                                extra_details=[("Organization", org.canonical_name if org else "—")],
                                confirm_url=url_for("person_delete", person_id=person_id) + f"?next={next_url}",
                                confirm_label="Yes, delete this contact",
                                cancel_url=next_url)
    finally:
        db.close()


def suggest_scoring_defaults(db, org_id: str) -> dict:
    """Heuristic starting point for the scoring form, derived from data actually loaded
    for this bank (contact reachability, outreach warmth, open signals) — never treated
    as authoritative. The form always shows these as editable and the person scoring the
    account is expected to review and adjust before saving."""
    persons = db.query(models.Person).filter(models.Person.current_org_id == org_id).all()
    total = len(persons) or 1
    reachable = sum(1 for p in persons if p.primary_email or p.phone)
    persona_reachability = round(reachable / total * 100, 1)

    person_ids = [p.id for p in persons]
    warm = 0
    if person_ids:
        channels = db.query(models.OutreachChannel).filter(
            models.OutreachChannel.person_id.in_(person_ids)).all()
        for c in channels:
            if c.stage and any(k in c.stage.lower() for k in ("repl", "accept", "meeting", "read")):
                warm += 1
    relationship_warmth = round(min(100, warm * 15), 1)

    signals = db.query(models.Signal).filter(models.Signal.org_id == org_id).all()
    unactioned = [s for s in signals if not s.is_actioned]
    high = [s for s in unactioned if s.urgency == "HIGH"]
    medium = [s for s in unactioned if s.urgency == "MEDIUM"]
    signal_strength = round(min(100, len(high) * 25 + len(medium) * 12 + len(unactioned) * 5), 1)

    regulatory_signals = [s for s in signals if s.signal_type == "regulatory"]
    regulatory_pressure = round(min(100, len(regulatory_signals) * 30), 1)

    return {
        "signal_strength": signal_strength, "regulatory_pressure": regulatory_pressure,
        "regulatory_mandatory": False,
        "persona_reachability": persona_reachability, "relationship_warmth": relationship_warmth,
        "ics": 50, "stage": "EXPLORING", "budget_status": "UNKNOWN",
        "entrenchment_score": 0, "risk_exposure": 0, "window_state": "",
        "strategic_readiness": 50, "capital_cost": 1,
    }


SIGNAL_TYPES_LABELS = {"leadership_change": "Leadership change", "regulatory": "Regulatory",
                        "product_launch": "Product launch", "hiring": "Hiring", "funding": "Funding",
                        "partnership": "Partnership", "rfp": "RFP / Tender", "expansion": "Expansion",
                        "earnings": "Earnings", "other": "Other"}


def _parse_date(raw: str | None):
    if not raw or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def apply_signal_intel_fields(sig, form) -> None:
    """Populates the SIG-TENDER and SIG-PARTNER fields on a Signal from submitted form
    data — shared by signal_new and signal_edit so the two routes can't drift apart.
    Fields for whichever signal_type ISN'T selected are cleared rather than left stale, so
    switching a signal's type doesn't leave orphaned tender/partnership data behind.

    Tender fields (SIG-TENDER, OPEN-GAP-SIG-02) are taken as-is from the form — there's no
    inference here, just structured capture of what a human already knows about an RFP.

    Partnership classification (SIG-PARTNER, OPEN-GAP-SIG-06) auto-runs the competitor/
    complementary/regulatory/neutral classifier (etl/signal_intel.py) against the title +
    summary text UNLESS the form explicitly overrides it — the override dropdown defaults
    to "Auto-detect", so re-saving an edited signal re-classifies from the latest text."""
    if sig.signal_type == "rfp":
        sig.deadline = _parse_date(form.get("deadline"))
        sig.estimated_value = form.get("estimated_value", "").strip() or None
        sig.scope_description = form.get("scope_description", "").strip() or None
        sig.contact_person = form.get("contact_person", "").strip() or None
        sig.source_of_knowledge = form.get("source_of_knowledge", "").strip() or None
    else:
        sig.deadline = None
        sig.estimated_value = None
        sig.scope_description = None
        sig.contact_person = None
        sig.source_of_knowledge = None

    if sig.signal_type == "partnership":
        override = form.get("partner_classification", "").strip() or None
        if override:
            sig.partner_classification = override
            sig.partner_classification_matched_vendor = None
        else:
            result = classify_partnership(sig.title, sig.summary)
            sig.partner_classification = result["classification"]
            sig.partner_classification_matched_vendor = result["matched_vendor"]
    else:
        sig.partner_classification = None
        sig.partner_classification_matched_vendor = None


def default_urgency_for_signal(sig) -> str:
    """RFPs default to CRITICAL (the buying decision is already made, per the Bible's
    SIG-TENDER spec). A partnership classified as COMPETITIVE_CLOSURE defaults to CRITICAL
    too — a competitor may be closing this account. Everything else defaults to MEDIUM,
    same as before this feature existed. Only applies when the form left urgency blank —
    an explicit human choice always wins."""
    if sig.signal_type == "rfp":
        return "CRITICAL"
    if sig.signal_type == "partnership" and sig.partner_classification == "COMPETITIVE_CLOSURE":
        return "CRITICAL"
    return "MEDIUM"


@app.route("/bank/<org_id>/signal/new", methods=["GET", "POST"])
def signal_new(org_id):
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404

        if request.method == "POST":
            sig = models.Signal(
                org_id=org_id,
                signal_type=request.form.get("signal_type", "").strip() or "other",
                source=request.form.get("source", "").strip() or None,
                title=request.form.get("title", "").strip() or None,
                summary=request.form.get("summary", "").strip() or None,
                url=request.form.get("url", "").strip() or None,
                product_match=request.form.get("product_match", "").strip() or None,
                is_actioned=request.form.get("is_actioned") == "on",
            )
            apply_signal_intel_fields(sig, request.form)
            sig.urgency = request.form.get("urgency", "").strip() or default_urgency_for_signal(sig)
            db.add(sig)
            db.flush()  # populate sig.created_at (column default) before stamping decay off of it
            stamp_signal_intelligence(sig)
            acc = db.get(models.AccountIntelligence, org_id)
            if acc:
                acc.last_signal_at = datetime.utcnow()
            db.commit()
            return redirect(url_for("bank_detail", org_id=org_id))

        return render_template("signal_edit.html", org=org, signal=None, org_id=org_id,
                                signal_types=SIGNAL_TYPES, signal_type_labels=SIGNAL_TYPES_LABELS,
                                urgencies=SIGNAL_URGENCIES)
    finally:
        db.close()


@app.route("/signal/<signal_id>/edit", methods=["GET", "POST"])
def signal_edit(signal_id):
    db = SessionLocal()
    try:
        sig = db.get(models.Signal, signal_id)
        if not sig:
            return "Signal not found", 404
        org = db.get(models.Organization, sig.org_id) if sig.org_id else None

        if request.method == "POST":
            sig.signal_type = request.form.get("signal_type", "").strip() or "other"
            sig.source = request.form.get("source", "").strip() or None
            sig.title = request.form.get("title", "").strip() or None
            sig.summary = request.form.get("summary", "").strip() or None
            sig.url = request.form.get("url", "").strip() or None
            sig.product_match = request.form.get("product_match", "").strip() or None
            sig.is_actioned = request.form.get("is_actioned") == "on"
            apply_signal_intel_fields(sig, request.form)
            sig.urgency = request.form.get("urgency", "").strip() or default_urgency_for_signal(sig)
            stamp_signal_intelligence(sig)  # re-stamp on every edit: signal_type may have changed
            db.commit()
            return redirect(url_for("bank_detail", org_id=sig.org_id) if sig.org_id else url_for("initiatives_page"))

        return render_template("signal_edit.html", org=org, signal=sig, org_id=sig.org_id,
                                signal_types=SIGNAL_TYPES, signal_type_labels=SIGNAL_TYPES_LABELS,
                                urgencies=SIGNAL_URGENCIES)
    finally:
        db.close()


@app.route("/signal/<signal_id>/toggle", methods=["POST"])
def signal_toggle(signal_id):
    db = SessionLocal()
    try:
        sig = db.get(models.Signal, signal_id)
        if not sig:
            return "Signal not found", 404
        sig.is_actioned = not sig.is_actioned
        db.commit()
        next_url = request.values.get("next") or (
            url_for("bank_detail", org_id=sig.org_id) if sig.org_id else url_for("initiatives_page"))
        return redirect(next_url)
    finally:
        db.close()


SCORING_STAGES = ["EVALUATING", "SHORTLISTING", "DEFINING", "EXPLORING", "AWARE", "UNAWARE",
                   "PROCUREMENT", "NEGOTIATION", "CLOSED"]
SCORING_BUDGET_STATUSES = ["ALLOCATED", "APPROVED", "SEEKING", "UNKNOWN", "UNFUNDED"]
SCORING_WINDOW_STATES = ["", "OPEN", "CLOSING", "OPENING", "CLOSED", "CLOSED_AGAIN"]


@app.route("/bank/<org_id>/score/edit", methods=["GET", "POST"])
def score_edit(org_id):
    """Live Bible scoring — computes Effective Opportunity and Decision Score using
    scoring.py's exact formula against modifiers.json's lookup tables. The form pre-fills
    with data-derived suggestions (see suggest_scoring_defaults) but every field is editable
    and nothing here is fabricated — it's a starting point for a human judgment call."""
    db = SessionLocal()
    try:
        org = db.get(models.Organization, org_id)
        if not org:
            return "Organization not found", 404
        acc = db.get(models.AccountIntelligence, org_id)
        if not acc:
            acc = models.AccountIntelligence(org_id=org_id)
            db.add(acc)
            db.flush()

        if request.method == "POST":
            def f(name, default=0.0):
                raw = request.form.get(name, "").strip()
                try:
                    return float(raw) if raw != "" else default
                except ValueError:
                    return default

            signal_strength = f("signal_strength")
            regulatory_pressure = f("regulatory_pressure")
            persona_reachability = f("persona_reachability")
            relationship_warmth = f("relationship_warmth")
            regulatory_mandatory = request.form.get("regulatory_mandatory") == "on"
            ics = f("ics", 50)
            stage = request.form.get("stage") or "EXPLORING"
            budget_status = request.form.get("budget_status") or "UNKNOWN"
            entrenchment_score = f("entrenchment_score", 0)
            risk_exposure = f("risk_exposure", 0)
            window_state = request.form.get("window_state") or None
            strategic_readiness = f("strategic_readiness", 50)
            capital_cost = f("capital_cost", 1) or 1

            dscore = scoring.dynamic_score(signal_strength, regulatory_pressure,
                                            persona_reachability, relationship_warmth,
                                            regulatory_mandatory=regulatory_mandatory)
            eff_opp = scoring.effective_opportunity(scoring.EffectiveOpportunityInputs(
                dynamic_score=dscore, ics=ics, stage=stage, budget_status=budget_status,
                entrenchment_score=entrenchment_score, risk_exposure=risk_exposure,
                window_state=window_state,
            ))
            dec_score = scoring.decision_score(eff_opp, strategic_readiness, capital_cost)
            priority = scoring.tier_for_score(eff_opp, ics)

            acc.effective_opportunity = eff_opp
            acc.decision_score = dec_score
            acc.priority = priority
            acc.score = int(round(min(100, max(0, eff_opp))))
            acc.readiness = int(round(strategic_readiness))
            acc.scoring_inputs = {
                "signal_strength": signal_strength, "regulatory_pressure": regulatory_pressure,
                "regulatory_mandatory": regulatory_mandatory,
                "persona_reachability": persona_reachability, "relationship_warmth": relationship_warmth,
                "dynamic_score": dscore, "ics": ics, "stage": stage, "budget_status": budget_status,
                "entrenchment_score": entrenchment_score, "risk_exposure": risk_exposure,
                "window_state": window_state, "strategic_readiness": strategic_readiness,
                "capital_cost": capital_cost,
            }
            acc.scored_at = datetime.utcnow()

            db.add(models.AccountScore(
                org_id=org_id,
                signal_score=int(round(min(35, signal_strength * 0.35))),
                regulatory_score=int(round(min(30, regulatory_pressure * 0.30))),
                reachability_score=int(round(min(20, persona_reachability * 0.20))),
                relationship_score=int(round(min(15, relationship_warmth * 0.15))),
                total_score=int(round(min(100, max(0, eff_opp)))), tier=priority,
                notes=f"Decision Score {dec_score} — Stage {stage}, Budget {budget_status}",
            ))

            db.commit()
            return redirect(url_for("bank_detail", org_id=org_id))

        inputs = acc.scoring_inputs or suggest_scoring_defaults(db, org_id)
        is_suggested = not bool(acc.scoring_inputs)
        history = (db.query(models.AccountScore).filter(models.AccountScore.org_id == org_id)
                   .order_by(models.AccountScore.score_date.desc()).limit(10).all())

        return render_template(
            "score_edit.html", org=org, acc=acc, inputs=inputs, is_suggested=is_suggested,
            history=history, stages=SCORING_STAGES, budget_statuses=SCORING_BUDGET_STATUSES,
            window_states=SCORING_WINDOW_STATES,
        )
    finally:
        db.close()


@app.route("/persons")
def persons_page():
    db = SessionLocal()
    try:
        org_filter = request.args.get("org", "").strip()
        q = db.query(models.Person)
        if org_filter:
            q = q.filter(models.Person.current_org_id == org_filter)
        q, filt = apply_filters(q, request.args)
        q = q.order_by(models.Person.priority_score.desc().nullslast(), models.Person.full_name)

        page = int(request.args.get("page", 1) or 1)
        people, total_count, total_pages, page = paginate(q, page)

        org_ids = {p.current_org_id for p in people if p.current_org_id}
        org_map = {o.id: o.canonical_name for o in db.query(models.Organization)
                   .filter(models.Organization.id.in_(org_ids)).all()} if org_ids else {}

        orgs = db.query(models.Organization).order_by(models.Organization.canonical_name).all()

        base_params = {k: v for k, v in [("q", filt["search"]), ("tier", filt["tier_filter"]),
                                          ("seniority", filt["seniority_filter"]), ("org", org_filter),
                                          ("indian", "1" if filt["indian_only"] else "")] if v}

        return render_template(
            "persons.html", persons=[person_row(p, org_map) for p in people], show_org=True,
            search=filt["search"], tier_filter=filt["tier_filter"], seniority_filter=filt["seniority_filter"],
            indian_only=filt["indian_only"], org_filter=org_filter, orgs=orgs,
            page=page, total_pages=total_pages, total_count=total_count,
            base_url_params=urlencode(base_params),
        )
    finally:
        db.close()


@app.route("/person/<person_id>/edit", methods=["GET", "POST"])
def person_edit(person_id):
    db = SessionLocal()
    try:
        p = db.get(models.Person, person_id)
        if not p:
            return "Person not found", 404

        next_url = request.values.get("next") or url_for("persons_page")

        existing_channels = db.query(models.OutreachChannel).filter(
            models.OutreachChannel.person_id == person_id).all()
        channels_by_key = {c.channel: c for c in existing_channels}

        if request.method == "POST":
            p.primary_email = request.form.get("primary_email", "").strip() or None
            p.phone = request.form.get("phone", "").strip() or None
            p.linkedin_url = request.form.get("linkedin_url", "").strip() or None
            p.next_step = request.form.get("next_step", "").strip() or None
            updated_by = request.form.get("updated_by", "").strip() or None

            for ch in OUTREACH_CHANNELS:
                stage = request.form.get(f"{ch}_stage", "").strip() or None
                notes = request.form.get(f"{ch}_notes", "").strip() or None
                ch_next_step = request.form.get(f"{ch}_next_step", "").strip() or None
                row = channels_by_key.get(ch)

                if not (stage or notes or ch_next_step):
                    continue  # nothing entered for this channel — don't create an empty row

                if not row:
                    row = models.OutreachChannel(person_id=person_id, channel=ch)
                    db.add(row)
                    channels_by_key[ch] = row

                row.stage = stage
                row.notes = notes
                row.next_step = ch_next_step
                row.updated_by = updated_by
                row.updated_at = datetime.utcnow()

            db.flush()
            p.last_activity_summary = build_activity_summary(channels_by_key)

            db.commit()
            return redirect(next_url)

        org = db.get(models.Organization, p.current_org_id) if p.current_org_id else None
        return render_template(
            "person_edit.html", p=p, org=org, next_url=next_url,
            channels=channels_by_key, channel_order=OUTREACH_CHANNELS,
            channel_labels=OUTREACH_CHANNEL_LABELS, stage_suggestions=OUTREACH_STAGE_SUGGESTIONS,
        )
    finally:
        db.close()


@app.route("/connectors")
def connectors_page():
    db = SessionLocal()
    try:
        people = db.query(models.Person).filter(models.Person.is_connector == True).all()  # noqa: E712
        org_ids = {p.current_org_id for p in people if p.current_org_id}
        org_map = {o.id: o.canonical_name for o in db.query(models.Organization)
                   .filter(models.Organization.id.in_(org_ids)).all()} if org_ids else {}
        rows = [{
            "full_name": p.full_name, "current_title": p.current_title,
            "organization": org_map.get(p.current_org_id, ""), "primary_email": p.primary_email,
            "mobile_phone": p.phone, "linkedin_url": p.linkedin_url,
            "decimal_relationship_status": "identified",
        } for p in people]
        return render_template("connectors.html", connectors=rows)
    finally:
        db.close()


@app.route("/initiatives")
def initiatives_page():
    db = SessionLocal()
    try:
        signals = (db.query(models.Signal).filter(models.Signal.org_id.isnot(None))
                   .order_by(models.Signal.created_at.desc()).limit(200).all())
        org_ids = {s.org_id for s in signals}
        org_map = {o.id: o.canonical_name for o in db.query(models.Organization)
                   .filter(models.Organization.id.in_(org_ids)).all()} if org_ids else {}
        rows = [signal_to_initiative(s, bank_name=org_map.get(s.org_id), org_id=s.org_id) for s in signals]
        return render_template("initiatives.html", initiatives=rows)
    finally:
        db.close()


UPLOAD_STATUS_LABELS = {"pending": "Pending", "processing": "Processing",
                         "processed": "Processed", "failed": "Failed"}


@app.route("/uploads")
def uploads_page():
    db = SessionLocal()
    try:
        status_filter = request.args.get("status", "").strip()
        q = db.query(models.DocumentUpload)
        if status_filter:
            q = q.filter(models.DocumentUpload.status == status_filter)
        uploads = q.order_by(models.DocumentUpload.created_at.desc()).all()

        org_ids = {u.org_id for u in uploads if u.org_id}
        org_map = {o.id: o.canonical_name for o in db.query(models.Organization)
                   .filter(models.Organization.id.in_(org_ids)).all()} if org_ids else {}

        rows = [{
            "id": u.id, "filename": u.filename, "file_size": u.file_size,
            "org_id": u.org_id, "org_name": org_map.get(u.org_id) or u.org_name_hint,
            "uploaded_by": u.uploaded_by, "notes": u.notes,
            "status": u.status, "status_label": UPLOAD_STATUS_LABELS.get(u.status, u.status),
            "processing_notes": u.processing_notes,
            "created_at": u.created_at, "processed_at": u.processed_at,
            "import_kind": u.import_kind or "contacts",
            "is_contact_file": u.filename.lower().endswith((".xlsx", ".xlsm", ".csv")),
        } for u in uploads]

        pending_count = db.query(models.DocumentUpload).filter(models.DocumentUpload.status == "pending").count()

        return render_template("uploads_list.html", uploads=rows, status_filter=status_filter,
                                pending_count=pending_count)
    finally:
        db.close()


@app.route("/uploads/new", methods=["GET", "POST"])
def upload_new():
    """Upload entry point — shared by three different buttons that all land here with
    different query params to pre-configure the form:
      - Per-bank 'Upload intelligence' button: ?org_id=<id>
      - Homepage 'Upload multi-bank vendor/subsidiary file' button: ?import_kind=ecosystem,
        deliberately with NO org_id — the file itself carries a Bank/Vendor Name column per
        row, so no single bank needs to be picked up front. import_ecosystem_from_bytes (and
        import_contacts_from_bytes, for that matter) already fall back to a per-row Company/
        Bank column before falling back to whatever bank was selected here, so this isn't new
        importer logic — just no longer forcing a single-bank choice at upload time.
      - Per-bank 'Upload PDF' / 'Upload image' buttons: ?org_id=<id>&filetype=pdf|image —
        restricts the file picker and adjusts the copy, but these still land as Pending like
        any other unstructured document; there's no OCR/parsing built in, so getting them into
        the dashboard still means sharing the file with Claude in a chat, same as the SNB
        dossier was done."""
    db = SessionLocal()
    try:
        preselect_org_id = request.args.get("org_id", "").strip() or None
        preselect_import_kind = request.args.get("import_kind", "").strip() or None
        if preselect_import_kind not in ("contacts", "ecosystem"):
            preselect_import_kind = None
        filetype = request.args.get("filetype", "").strip() or None
        if filetype not in ("pdf", "image"):
            filetype = None

        if request.method == "POST":
            f = request.files.get("file")
            if not f or not f.filename:
                orgs = db.query(models.Organization).order_by(models.Organization.canonical_name).all()
                return render_template("upload_new.html", orgs=orgs, preselect_org_id=preselect_org_id,
                                        preselect_import_kind=preselect_import_kind, filetype=filetype,
                                        error="Choose a file to upload.")

            data = f.read()
            org_id = request.form.get("org_id", "").strip() or None
            org_name_hint = request.form.get("org_name_hint", "").strip() or None
            if org_id:
                org = db.get(models.Organization, org_id)
                org_name_hint = org.canonical_name if org else org_name_hint

            import_kind = request.form.get("import_kind", "contacts").strip() or "contacts"
            if import_kind not in ("contacts", "ecosystem"):
                import_kind = "contacts"

            upload = models.DocumentUpload(
                org_id=org_id, org_name_hint=org_name_hint, import_kind=import_kind,
                filename=f.filename, content_type=f.content_type,
                file_size=len(data), file_data=data,
                uploaded_by=request.form.get("uploaded_by", "").strip() or None,
                notes=request.form.get("notes", "").strip() or None,
                status="pending",
            )
            db.add(upload)

            # PDFs/images are read immediately, right here in the request — rule-based text
            # extraction + org-name detection (etl/document_reader.py), no AI/API key, no chat
            # round-trip. Decided by the actual file extension, not the filetype query param,
            # so this fires no matter which button was used to get here. Wrapped in try/except
            # so a corrupt/unreadable file still gets saved (status='failed' with the real error)
            # instead of losing the upload entirely.
            doc_type = is_document_file(f.filename)
            if doc_type is not None:
                try:
                    process_uploaded_document(upload, bank_name=org_name_hint)
                except Exception as e:
                    upload.status = "failed"
                    upload.processing_notes = f"Couldn't read this file automatically: {e}"

            db.commit()

            # Land straight back on the bank page (where the summary + detected connections now
            # show up) instead of the uploads list — that's the whole point of reading it immediately.
            if doc_type is not None and org_id:
                return redirect(url_for("bank_detail", org_id=org_id) + "#document-intelligence")
            return redirect(url_for("uploads_page"))

        orgs = db.query(models.Organization).order_by(models.Organization.canonical_name).all()
        return render_template("upload_new.html", orgs=orgs, preselect_org_id=preselect_org_id,
                                preselect_import_kind=preselect_import_kind, filetype=filetype, error=None)
    finally:
        db.close()


@app.route("/uploads/<upload_id>/download")
def upload_download(upload_id):
    db = SessionLocal()
    try:
        u = db.get(models.DocumentUpload, upload_id)
        if not u:
            abort(404)
        return send_file(io.BytesIO(u.file_data), download_name=u.filename,
                          mimetype=u.content_type or "application/octet-stream", as_attachment=True)
    finally:
        db.close()


@app.route("/uploads/<upload_id>/process-contacts", methods=["POST"])
def upload_process_contacts(upload_id):
    """One-click processing for structured contact-list files (.xlsx/.csv, same
    shape as the bank LinkedIn exports) — runs entirely on the server with the
    same deterministic column-matching logic as etl/import_incoming.py. No AI,
    no API key, no command line: this is instant because it's just parsing a
    spreadsheet, not reading an unstructured dossier."""
    db = SessionLocal()
    try:
        u = db.get(models.DocumentUpload, upload_id)
        if not u:
            abort(404)

        institution_hint = None
        if u.org_id:
            org = db.get(models.Organization, u.org_id)
            institution_hint = org.canonical_name if org else None
        institution_hint = institution_hint or u.org_name_hint

        # institution_hint is allowed to be None here — both importers fall back to a
        # per-row Bank/Company column before falling back to this, which is exactly what
        # makes a single multi-bank file work without picking one bank up front. If a file
        # genuinely has no way to place any row (no bank hint AND no per-row column), the
        # importer itself reports that via rows_skipped / an explicit error, rather than us
        # refusing to even try.
        if (u.import_kind or "contacts") == "ecosystem":
            result = import_ecosystem_from_bytes(db, u.file_data, u.filename, institution_hint)
            if result.get("error"):
                u.status = "failed"
                u.processing_notes = result["error"]
            else:
                u.status = "processed"
                u.processed_at = datetime.utcnow()
                u.processing_notes = (
                    f"Auto-processed: {result['vendors_created']} vendor/subsidiary org(s) created, "
                    f"{result['relationships_updated']} existing connection(s) updated, "
                    f"{result['banks_created']} new bank(s) created, "
                    f"{result['rows_skipped_missing_required_fields']} row(s) skipped (missing name/bank)."
                )
        else:
            result = import_contacts_from_bytes(db, u.file_data, u.filename, institution_hint)
            if result.get("error"):
                u.status = "failed"
                u.processing_notes = result["error"]
            else:
                u.status = "processed"
                u.processed_at = datetime.utcnow()
                u.processing_notes = (
                    f"Auto-processed: {result['people_created']} contact(s) created, "
                    f"{result['people_updated']} updated, {result['orgs_created']} new bank(s) created, "
                    f"{result['rows_skipped_missing_required_fields']} row(s) skipped (missing name/bank)."
                )

        if u.status == "processed" and not u.org_id and institution_hint:
            matched_org = db.query(models.Organization).filter(
                models.Organization.canonical_name.ilike(institution_hint)).first()
            if matched_org:
                u.org_id = matched_org.id
        db.commit()
        return redirect(url_for("uploads_page"))
    finally:
        db.close()


@app.route("/uploads/<upload_id>/status", methods=["POST"])
def upload_status(upload_id):
    db = SessionLocal()
    try:
        u = db.get(models.DocumentUpload, upload_id)
        if not u:
            abort(404)
        new_status = request.form.get("status", "").strip()
        if new_status in UPLOAD_STATUS_LABELS:
            u.status = new_status
        u.processing_notes = request.form.get("processing_notes", "").strip() or None
        if new_status == "processed":
            u.processed_at = datetime.utcnow()
            org_id = request.form.get("org_id", "").strip() or None
            if org_id:
                u.org_id = org_id
        db.commit()
        return redirect(url_for("uploads_page"))
    finally:
        db.close()


if __name__ == "__main__":
    # Only auto-create tables on SQLite (local dev convenience). On Postgres, Alembic is the
    # single source of truth for schema -- letting create_all() touch it too is what caused the
    # "relation already exists" errors: it can create a table moments before a migration tries
    # to create the same one, and create_all() doesn't update alembic_version, so Alembic then
    # thinks that migration was never applied.
    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    app.run(host="127.0.0.1", port=5050, debug=True)
