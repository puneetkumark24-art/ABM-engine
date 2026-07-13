"""
documented_contacts_seed.py — loads the ~20 real KSA contacts that exist only
as prior BD research notes (project memory), not in any machine-readable file.

Phase 1 discovery found `contacts` in the live decimal_abm DB has 1 row (a
test contact) and `abm_contacts.xlsx` has the same single test row — the
documented research was never structured into either. This script recovers
it from where it actually lives: Puneet's own prior research, transcribed
here rather than re-scraped, per PRD Golden Rule "reuse existing work."

Emails/phones are intentionally left blank (email_confidence="Unknown") —
none were captured in the source notes; do not guess.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
import models

DOCUMENTED_CONTACTS = [
    # (full_name, title, org_canonical_name, seniority_level, persona, notes)
    ("Al-Mogbel", "CEO", "Al Rajhi Bank", "c_suite", "Decision Maker", None),
    ("Al-Furaiji", "CDO", "Al Rajhi Bank", "c_suite", "Decision Maker", None),
    ("Abid Shakeel", "CSO", "Al Rajhi Bank", "c_suite", "Champion",
     "KEY BRIDGE — ex-Deloitte"),
    ("Al-Omari", "COO", "Al Rajhi Bank", "c_suite", "Decision Maker", None),
    ("Al-Dhfayan", "Acting CDO", "Al Rajhi Bank", "c_suite", "Decision Maker", None),
    ("Al-Rajhi", "GM Retail", "Al Rajhi Bank", "director", "Influencer", None),
    ("Al-Fadda", "CFO", "Al Rajhi Bank", "c_suite", "Decision Maker", None),
    ("Alomar", "CTO", "Al Rajhi Bank", "c_suite", "Influencer", None),

    ("Mazen Pharaon", "CDO", "Riyad Bank", "c_suite", "Champion",
     "KEY BRIDGE — ex-Deloitte"),
    ("Al-Ghamdi", "Chief Wholesale Banking Officer", "Riyad Bank", "c_suite", "Decision Maker", None),
    ("Al-Dhubaib", "Chief Retail Banking Officer", "Riyad Bank", "c_suite", "Decision Maker", None),
    ("Kashgari", "SVP Digital", "Riyad Bank", "svp_evp", "Influencer", None),
    ("Barakat", "EVP Technology", "Riyad Bank", "svp_evp", "Influencer", None),

    ("Rasha Abu AlSaud", "Group Head of Digital", "Saudi National Bank (SNB)", "svp_evp", "Decision Maker", None),
    ("Saud Bajbair", "CTO", "Saudi National Bank (SNB)", "c_suite", "Influencer", None),

    ("Yasser Alshalaan", "CTO", "Hala", "c_suite", "Decision Maker", None),

    # Connectors — not employed at target banks; warm-path intermediaries
    ("Khalid Al Khalaf", "—", "Mastercard", "director", "Connector", None),
    ("Eemaan AlBaker", "—", "Mastercard", "director", "Connector", None),
    ("Fahad Aldesari", "—", "KPMG", "director", "Connector", "Confirmed phone number on file"),
    ("Harjit Kang", "—", "Mambu MEA", "director", "Connector", None),
]

CONNECTOR_ORGS = {"Mastercard", "KPMG", "Mambu MEA"}  # not KSA banks; create if missing


def run(db: Session) -> dict:
    created_orgs, created_persons, skipped = 0, 0, 0

    for full_name, title, org_name, seniority, persona, notes in DOCUMENTED_CONTACTS:
        org = db.query(models.Organization).filter(
            models.Organization.canonical_name == org_name).first()
        if not org:
            org = models.Organization(
                canonical_name=org_name,
                country="Saudi Arabia" if org_name not in CONNECTOR_ORGS else None,
                source="documented_contacts_seed (prior BD research)",
                verification_status="unverified",
            )
            db.add(org)
            db.flush()
            tag = "connector_org" if org_name in CONNECTOR_ORGS else "commercial_bank"
            db.add(models.OrgTypeTag(org_id=org.id, type_tag=tag))
            created_orgs += 1

        existing = db.query(models.Person).filter(
            models.Person.full_name == full_name,
            models.Person.current_org_id == org.id,
        ).first()
        if existing:
            skipped += 1
            continue

        person = models.Person(
            full_name=full_name,
            current_org_id=org.id,
            current_title=title,
            seniority_level=seniority,
            persona=persona,
            is_decision_maker=(persona == "Decision Maker"),
            is_influencer=(persona in ("Influencer", "Champion")),
            is_connector=(persona == "Connector"),
            email_confidence="Unknown",
            background_notes=notes,
            data_source="Prior BD research (project memory, June 2026)",
            warmness="Warm" if persona in ("Champion", "Connector") else "Cold",
        )
        db.add(person)
        created_persons += 1

    db.commit()
    return {"orgs_created": created_orgs, "persons_created": created_persons, "skipped_existing": skipped}
