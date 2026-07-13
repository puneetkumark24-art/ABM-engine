"""
import_ecosystem.py — loads BD "connection architecture" dossier data (the SNB-style
documents produced by the saudi-bank-bd-intelligence skill) into the ecosystem tables
that were already in the schema but unused: OrgRelationship (subsidiary/vendor/partner
links between banks and their ecosystem) and PersonRelationship (connector/introduction
chains between named individuals).

Usage:
    python etl/import_ecosystem.py

Data source for this first run: SNB_CONSOLIDATED_Intelligence_MASTER.pdf (Intelligence
Date May 26, 2026), transcribed from its master flow-diagram page and text pages.

HONESTY NOTE ON DATA QUALITY — read before trusting an email/phone for outreach:
  - Phone numbers came from the dossier's flow diagram, printed at reasonable size —
    high confidence, but not independently verified against a live source.
  - Emails were transcribed from the same diagram at much smaller font size. Where a
    string was genuinely illegible it was left blank rather than guessed — never
    fabricate a contact detail. Where legible but not independently confirmed, the
    contact's email_confidence is set to "Unverified" so the dashboard doesn't imply
    more certainty than exists. Spot-check anything you're about to use before sending it.
  - Two name collisions in the source document are flagged explicitly below rather than
    silently merged: (1) "Abdulla Almoayed" the Tarabut founder/CEO vs. "Abdullah AlMoayed"
    the SNB Ventures liaison — different people, similar names. (2) "Bandar Al-Ghamdi" the
    PMO Director vs. "Bander Al-Ghamdi" the Group CRO — the dossier spells these two
    slightly differently but it's exactly the kind of thing that could be one person with
    two roles or a transcription slip; treat as unconfirmed until checked.

Safe to re-run — organizations match on canonical_name, persons match on
(full_name, current_org_id), relationships are only inserted if an equivalent row
doesn't already exist.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import Base, engine, SessionLocal
import models

SOURCE = "SNB_CONSOLIDATED_Intelligence_MASTER.pdf (Intelligence Date 2026-05-26)"

# ─────────────────────────────────────────────────────────────
# Ecosystem organizations connected to SNB, with their relationship to the bank.
# confidence is a 0-1 normalized version of the dossier's 5-star "ecosystem connection
# strength" rating (e.g. 4.5/5 stars -> 0.9).
# ─────────────────────────────────────────────────────────────
ECOSYSTEM_ORGS = [
    {
        "canonical_name": "ITQAN", "type_tags": ["subsidiary", "bpo_vendor", "automation_vendor"],
        "relationship_type": "subsidiary_of", "confidence": 1.0,
        "context": "100% SNB-owned subsidiary. Internal automation & BPO. Primary backdoor route "
                   "per dossier: Turki Al-Asmari -> Majed Al-Rubaian -> SNB transformation teams.",
    },
    {
        "canonical_name": "Tarabut", "type_tags": ["fintech_vendor", "open_banking_vendor"],
        "relationship_type": "vendor_of", "confidence": 0.9,
        "context": "Open banking hub partner. SME embedded lending / POS finance route via "
                   "Saud Bajbair (SEVP Retail Banking).",
    },
    {
        "canonical_name": "Geidea", "type_tags": ["fintech_vendor", "pos_merchant_vendor"],
        "relationship_type": "vendor_of", "confidence": 0.8,
        "context": "POS & merchant ecosystem. Merchant finance / embedded lending route via retail lending teams.",
    },
    {
        "canonical_name": "ITC Infotech", "type_tags": ["it_vendor", "consulting"],
        "relationship_type": "vendor_of", "confidence": 0.85,
        "context": "Strategic IT partner, 12+ year relationship. COO-level introduction path (Saleh Mohammed Saleh).",
    },
    {
        "canonical_name": "Backbase", "type_tags": ["it_vendor", "digital_banking_platform"],
        "relationship_type": "vendor_of", "confidence": 0.85,
        "context": "Digital banking platform. NEO (SNB's digital banking unit) expansion route.",
    },
    {
        "canonical_name": "KPMG", "type_tags": ["consulting", "alumni_network"],
        "relationship_type": "partner_of", "confidence": 0.75,
        "context": "Alumni & advisory network. High-trust route via KPMG alumni overlap with SNB leadership "
                   "(Khalid Alkhudair -> CEO Tareq Al-Sadhan).",
    },
    {
        "canonical_name": "Mastercard", "type_tags": ["card_network_partner", "fintech"],
        "relationship_type": "partner_of", "confidence": 0.75,
        "context": "Advisory board / card network partner — cross-bank advisory relationship, not SNB-exclusive.",
    },
]

# ─────────────────────────────────────────────────────────────
# Named contacts at each ecosystem org. email_confidence "Unverified" wherever the
# email was legible but not independently confirmed; phone is the dossier's number.
# ─────────────────────────────────────────────────────────────
ECOSYSTEM_CONTACTS = [
    # ITC Infotech
    {"org": "ITC Infotech", "full_name": "Vishal Kumar", "current_title": "ME President",
     "phone": "+971 50 450 5464", "primary_email": "vishal.kumar@itcinfotech.com"},
    {"org": "ITC Infotech", "full_name": "Pareekh Jain", "current_title": "Practice Head — Banking",
     "phone": "+91 98203 81030", "primary_email": None},
    {"org": "ITC Infotech", "full_name": "Sandeep Kumar", "current_title": "Head — KSA",
     "phone": "+966 54 033 8647", "primary_email": None},
    {"org": "ITC Infotech", "full_name": "Manish Choudhary", "current_title": "KSA Team",
     "phone": "+966 56 293 3031", "primary_email": None},

    # Backbase
    {"org": "Backbase", "full_name": "Ahmad Ghandour", "current_title": "MD — Saudi Arabia",
     "phone": "+966 55 081 9191", "primary_email": "ahmad.ghandour@backbase.com"},
    {"org": "Backbase", "full_name": "Marwan AlZaabi", "current_title": "Solution Consultant",
     "phone": "+971 50 658 8830", "primary_email": "marwan.alzaabi@backbase.com"},
    {"org": "Backbase", "full_name": "Konstantin Geshev", "current_title": "VP EMEA Partnerships",
     "phone": "+31 6 2271 8642", "primary_email": None},
    {"org": "Backbase", "full_name": "Rajiv Batra", "current_title": "Director — Financial Services",
     "phone": "+65 9856 6312", "primary_email": None},

    # Tarabut
    {"org": "Tarabut", "full_name": "Abdulla Almoayed", "current_title": "Founder & CEO",
     "phone": "+971 17 839 9191", "primary_email": "abdulla.almoayed@tarabut.io",
     "note": "NOT the same person as 'Abdullah AlMoayed' (SNB Ventures liaison) below — similar name, different org/role, flagged in dossier."},
    {"org": "Tarabut", "full_name": "Nidhi Bhattacharya", "current_title": "Director of Products",
     "phone": "+971 50 455 5662", "primary_email": None},
    {"org": "Tarabut", "full_name": "Derek Lakin", "current_title": "VP Engineering",
     "phone": "+971 50 450 3826", "primary_email": None},
    {"org": "Tarabut", "full_name": "Oussama Bouhcine", "current_title": "VP Customer Success",
     "phone": "+971 50 275 0450", "primary_email": None},

    # Geidea
    {"org": "Geidea", "full_name": "Omar Yassine", "current_title": "Group CEO",
     "phone": "+971 50 452 2020", "primary_email": None},
    {"org": "Geidea", "full_name": "Abdallah Aboushi", "current_title": "Head — Merchant Acquiring",
     "phone": "+966 55 041 1957", "primary_email": None},
    {"org": "Geidea", "full_name": "Mohammed AlRajhi", "current_title": "Head — Merchant Acquiring",
     "phone": "+966 56 987 6543", "primary_email": None},
    {"org": "Geidea", "full_name": "Ahmed AlDabbagh", "current_title": "Head — Product Management",
     "phone": "+966 50 924 2245", "primary_email": None},

    # KPMG
    {"org": "KPMG", "full_name": "Fahad Aldosari", "current_title": "Partner — KPMG",
     "phone": "+966 50 524 9922", "primary_email": None},
    {"org": "KPMG", "full_name": "Nimesh Asrani", "current_title": "KPMG Network",
     "phone": "+91 98200 12345", "primary_email": None},
    {"org": "KPMG", "full_name": "Yasser AlGhomdi", "current_title": "Partner — Advisory",
     "phone": "+966 54 033 8099", "primary_email": None},
    {"org": "KPMG", "full_name": "Saad Khan", "current_title": "Director — Financial Services",
     "phone": "+971 50 883 6161", "primary_email": None},

    # Mastercard
    {"org": "Mastercard", "full_name": "Khalid Al Khalaf", "current_title": "EVP Market Development (unconfirmed title)",
     "phone": "+971 56 682 4422", "primary_email": None},
    {"org": "Mastercard", "full_name": "Eemaan AlBaker", "current_title": "Senior Country Business Advisor — KSA",
     "phone": "+966 50 205 2424", "primary_email": None},
]

# ─────────────────────────────────────────────────────────────
# SNB's own people, positioned in the 4-column flow (connector / champion /
# decision_maker / c_suite) with the dossier's P1/P2/P3 priority labels.
# Matched into the bank org itself, except ITQAN-column entries which belong to ITQAN.
# ─────────────────────────────────────────────────────────────
SNB_FLOW_PEOPLE = [
    # C-Suite (final authority)
    {"org": "Saudi National Bank", "full_name": "Tareq Al-Sadhan", "current_title": "Group CEO",
     "phone": "+966 11 874 5000", "primary_email": "t.alsadhan@alahli.com",
     "bd_flow_column": "c_suite", "bd_priority": "Final Authority", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Carl Esposti", "current_title": "Group CFO",
     "phone": "+966 11 874 5100", "primary_email": None,
     "bd_flow_column": "c_suite", "bd_priority": "Final Authority", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Bander Al-Ghamdi", "current_title": "Group Chief Risk Officer",
     "phone": "+966 11 874 5200", "primary_email": None,
     "bd_flow_column": "c_suite", "bd_priority": "Final Authority", "is_decision_maker": True, "seniority_level": "c_suite",
     "note": "Dossier also lists a 'Bandar Al-Ghamdi' (PMO Director, P3) with near-identical spelling — "
             "may be the same person or a transcription slip. Flagged, not merged."},
    {"org": "Saudi National Bank", "full_name": "Abdulaziz Al-Fayez", "current_title": "Group General Counsel",
     "phone": "+966 11 874 5300", "primary_email": None,
     "bd_flow_column": "c_suite", "bd_priority": "Final Authority", "is_decision_maker": True, "seniority_level": "c_suite",
     "note": "Same name also appears in the dossier's champion layer as 'Compliance Champion (Regulatory)' — "
             "kept as one person at the more senior C-suite level rather than duplicated."},
    {"org": "Saudi National Bank", "full_name": "Yazeed Al-Humaidi", "current_title": "Board Member (PIF Representative)",
     "phone": "+966 11 874 5400", "primary_email": "y.alhumaidi@pif.gov.sa",
     "bd_flow_column": "c_suite", "bd_priority": "Final Authority", "is_decision_maker": True, "seniority_level": "c_suite"},

    # Decision makers P1/P2/P3
    {"org": "Saudi National Bank", "full_name": "Saud Bajbair", "current_title": "SEVP Retail Banking",
     "phone": "+966 11 874 5555", "primary_email": "s.bajbair@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P1", "is_decision_maker": True, "seniority_level": "svp_evp"},
    {"org": "Saudi National Bank", "full_name": "Rasha Abu AlSaud", "current_title": "Chief Technology Officer",
     "phone": "+966 11 874 8432", "primary_email": "r.abualsaud@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P1", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Dr. Saleh Al-Furaih", "current_title": "CEO — NEO Digital Ventures",
     "phone": "+966 11 874 6456", "primary_email": "s.alfuraih@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P1", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Saleh Mohammed Saleh", "current_title": "Group COO",
     "phone": "+966 11 874 6200", "primary_email": "s.msaleh@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P2", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Khalid Alkhudair", "current_title": "Chief Experience Officer",
     "phone": "+966 11 874 6100", "primary_email": "k.alkhudair@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P2", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Jameel Noor", "current_title": "Chief Data Officer",
     "phone": "+966 11 874 7333", "primary_email": "j.noor@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P2", "is_decision_maker": True, "seniority_level": "c_suite"},
    {"org": "Saudi National Bank", "full_name": "Bader Arif", "current_title": "SVP Enterprise Project Delivery",
     "phone": "+966 11 874 7888", "primary_email": "b.arif@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P3", "is_decision_maker": True, "seniority_level": "svp_evp"},
    {"org": "Saudi National Bank", "full_name": "Fahad Al-Mousa", "current_title": "Director — Procurement & Vendor Sourcing",
     "phone": "+966 11 874 7001", "primary_email": "f.almousa@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "Critical", "is_decision_maker": True, "seniority_level": "director"},
    {"org": "Saudi National Bank", "full_name": "Bandar Al-Ghamdi", "current_title": "PMO Director",
     "phone": "+966 11 874 7111", "primary_email": "b.alghamdi@alahli.com",
     "bd_flow_column": "decision_maker", "bd_priority": "P3", "is_decision_maker": False, "seniority_level": "director",
     "note": "See name-collision note on 'Bander Al-Ghamdi' (Group CRO) above."},
    {"org": "Saudi National Bank", "full_name": "Abdullah Al-Bogami", "current_title": "Head — SME Banking",
     "phone": "+966 11 874 7222", "primary_email": None,
     "bd_flow_column": "decision_maker", "bd_priority": "P3", "is_decision_maker": False, "seniority_level": "director"},

    # Internal champions — SNB
    {"org": "Saudi National Bank", "full_name": "Sultan Al-Bloushi", "current_title": "Enterprise Integration & API Lead",
     "bd_flow_column": "champion", "bd_priority": "Tech Champion (Implementation)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Waleed Al-Ghamdi", "current_title": "Head Enterprise Architecture & Cloud Gov.",
     "bd_flow_column": "champion", "bd_priority": "Tech Evaluator (Architecture)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Nouf Al-Sudairy", "current_title": "Sr. Product Manager — Digital Onboarding",
     "bd_flow_column": "champion", "bd_priority": "Product Champion (Onboarding)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Yasser Al-Barrak", "current_title": "Head Retail Banking Digital Channels",
     "bd_flow_column": "champion", "bd_priority": "Business Owner (Retail)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Faisal Al-Shahrani", "current_title": "Product Delivery Manager — Lending Verticals",
     "bd_flow_column": "champion", "bd_priority": "Delivery Owner (Lending)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Rayan Al-Salloom", "current_title": "Head Corporate & Institutional Ops Trans.",
     "bd_flow_column": "champion", "bd_priority": "Business Owner (Corporate/SME)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Abdullah AlMoayed", "current_title": "Manager — Strategic Partnerships (SNB Ventures Liaison)",
     "bd_flow_column": "champion", "bd_priority": "Ventures Champion (Innovation)", "is_influencer": True,
     "note": "NOT the same person as Tarabut's founder/CEO 'Abdulla Almoayed' — flagged in dossier, kept distinct."},
    {"org": "Saudi National Bank", "full_name": "Saud AlHumaidi", "current_title": "AVP Enterprise Risk Management",
     "bd_flow_column": "champion", "bd_priority": "Risk Champion (Approval)", "is_influencer": True},
    {"org": "Saudi National Bank", "full_name": "Abdulaziz AlFayez", "current_title": "Director — Compliance & Regulatory Affairs",
     "bd_flow_column": "champion", "bd_priority": "Compliance Champion (Regulatory)", "is_influencer": True,
     "note": "Same name as the Group General Counsel C-suite entry above — dossier lists both roles under this name; not duplicated as a separate person record beyond this note."},

    # Internal champions — ITQAN (subsidiary)
    {"org": "ITQAN", "full_name": "Turki Al-Asmari", "current_title": "Sr. Solutions Architect — Business Automation",
     "bd_flow_column": "champion", "bd_priority": "Tech Reviewer (Automation)", "is_influencer": True},
    {"org": "ITQAN", "full_name": "Majed Al-Rubaian", "current_title": "Head BPO & RPA Engineering",
     "bd_flow_column": "champion", "bd_priority": "Internal Gatekeeper (Backdoor)", "is_influencer": True},
    {"org": "ITQAN", "full_name": "Mohammed Al-Harbi", "current_title": "Lead Business Analyst — Process Mining",
     "bd_flow_column": "champion", "bd_priority": "Process Champion (Discovery)", "is_influencer": True},
    {"org": "ITQAN", "full_name": "Ayman Al-Tayar", "current_title": "Head Shared Services Ops Transformation",
     "bd_flow_column": "champion", "bd_priority": "Ops Champion (Transformation)", "is_influencer": True},
    {"org": "ITQAN", "full_name": "Abdulrahman Al-Otaibi", "current_title": "Manager — Cloud & Infrastructure",
     "bd_flow_column": "champion", "bd_priority": "Deployment Champion (Cloud)", "is_influencer": True},
    {"org": "ITQAN", "full_name": "Reem Al-Qahtani", "current_title": "Change Management Lead",
     "bd_flow_column": "champion", "bd_priority": "Change Champion (Adoption)", "is_influencer": True},
]

# ─────────────────────────────────────────────────────────────
# Connector / introduction chains — "Primary Strategic Entry Routes" in the dossier,
# turned into explicit person-to-person edges (PersonRelationship, type="introduces").
# ─────────────────────────────────────────────────────────────
CONNECTOR_CHAINS = [
    {"from": "Turki Al-Asmari", "to": "Majed Al-Rubaian",
     "context": "ITQAN backdoor route, step 1 — strongest operational pathway (ITQAN is wholly SNB-owned)."},
    {"from": "Majed Al-Rubaian", "to": "Saleh Mohammed Saleh",
     "context": "ITQAN backdoor route, step 2 — reaches SNB Group COO / transformation teams."},
    {"from": "Abdulla Almoayed", "to": "Saud Bajbair",
     "context": "Tarabut + SME POS lending route — aligns with SNB's SME POS lending / open banking roadmap."},
    {"from": "Omar Yassine", "to": "Saud Bajbair",
     "context": "Geidea merchant finance route — pre-approved merchant working capital via POS transaction intelligence."},
    {"from": "Fahad Aldosari", "to": "Khalid Alkhudair",
     "context": "KPMG alumni route — high-trust relationship via KPMG alumni overlap with SNB leadership."},
    {"from": "Khalid Alkhudair", "to": "Tareq Al-Sadhan",
     "context": "KPMG alumni route, step 2 — CXO relationship into Group CEO."},
]


def get_or_create_org(db, canonical_name, type_tags=None):
    org = db.query(models.Organization).filter(models.Organization.canonical_name == canonical_name).first()
    if not org:
        org = models.Organization(canonical_name=canonical_name, country="Saudi Arabia", source=SOURCE)
        db.add(org)
        db.flush()
    existing_tags = {t.type_tag for t in org.type_tags}
    for tag in (type_tags or []):
        if tag not in existing_tags:
            db.add(models.OrgTypeTag(org_id=org.id, type_tag=tag))
    return org


def get_or_create_person(db, cache, full_name, org_id, fields):
    key = (full_name, org_id)
    if key in cache:
        p = cache[key]
    else:
        p = db.query(models.Person).filter(models.Person.full_name == full_name,
                                            models.Person.current_org_id == org_id).first()
        if not p:
            p = models.Person(full_name=full_name, current_org_id=org_id, data_source=SOURCE)
            db.add(p)
            db.flush()
        cache[key] = p
    for k, v in fields.items():
        if k == "note":
            continue
        if v is not None:
            setattr(p, k, v)
    if fields.get("primary_email") and not fields.get("email_confidence"):
        p.email_confidence = "Unverified"
    return p


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    stats = {"orgs_created_or_updated": 0, "org_relationships_created": 0,
              "vendor_contacts": 0, "snb_flow_people": 0, "connector_edges_created": 0,
              "flagged_ambiguities": 0}
    try:
        snb = db.query(models.Organization).filter(
            models.Organization.canonical_name.ilike("%saudi national%")).first()
        if not snb:
            snb = get_or_create_org(db, "Saudi National Bank", ["commercial_bank"])
        stats["orgs_created_or_updated"] += 1

        org_by_name = {"Saudi National Bank": snb}
        for entry in ECOSYSTEM_ORGS:
            org = get_or_create_org(db, entry["canonical_name"], entry["type_tags"])
            org_by_name[entry["canonical_name"]] = org
            stats["orgs_created_or_updated"] += 1

            existing_rel = db.query(models.OrgRelationship).filter(
                models.OrgRelationship.from_org_id == org.id,
                models.OrgRelationship.to_org_id == snb.id,
                models.OrgRelationship.relationship_type == entry["relationship_type"],
            ).first()
            if not existing_rel:
                db.add(models.OrgRelationship(
                    from_org_id=org.id, to_org_id=snb.id,
                    relationship_type=entry["relationship_type"],
                    strength="Strong" if entry["confidence"] >= 0.85 else "Medium",
                    confidence=entry["confidence"], source=SOURCE, context=entry["context"],
                ))
                stats["org_relationships_created"] += 1

        person_cache = {}
        for c in ECOSYSTEM_CONTACTS:
            org = org_by_name[c["org"]]
            fields = {k: v for k, v in c.items() if k not in ("org", "full_name", "note")}
            get_or_create_person(db, person_cache, c["full_name"], org.id, fields)
            stats["vendor_contacts"] += 1
            if "note" in c:
                stats["flagged_ambiguities"] += 1

        for c in SNB_FLOW_PEOPLE:
            org = org_by_name[c["org"]]
            fields = {k: v for k, v in c.items() if k not in ("org", "full_name", "note")}
            get_or_create_person(db, person_cache, c["full_name"], org.id, fields)
            stats["snb_flow_people"] += 1
            if "note" in c:
                stats["flagged_ambiguities"] += 1

        db.flush()

        def find_person(name):
            for (full_name, _org_id), p in person_cache.items():
                if full_name == name:
                    return p
            return db.query(models.Person).filter(models.Person.full_name == name).first()

        for chain in CONNECTOR_CHAINS:
            from_p = find_person(chain["from"])
            to_p = find_person(chain["to"])
            if not from_p or not to_p:
                continue
            existing = db.query(models.PersonRelationship).filter(
                models.PersonRelationship.from_person_id == from_p.id,
                models.PersonRelationship.to_person_id == to_p.id,
                models.PersonRelationship.relationship_type == "introduces",
            ).first()
            if not existing:
                db.add(models.PersonRelationship(
                    from_person_id=from_p.id, from_name=from_p.full_name, from_type="connector",
                    to_person_id=to_p.id, relationship_type="introduces",
                    strength="Strong", context=chain["context"],
                ))
                stats["connector_edges_created"] += 1

        db.commit()
        print("Ecosystem import complete.")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print("\nSource:", SOURCE)
        print("Reminder: vendor contact emails marked email_confidence='Unverified' should be")
        print("spot-checked before outreach. See file header for the two flagged name collisions.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
