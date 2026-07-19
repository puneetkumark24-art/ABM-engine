"""
routers/master_data.py — Master Data Management (mission Step 9).

Full lifecycle for the two core entities (banks/organizations, people) plus the
vendor ecosystem view:
  • PATCH  — whitelisted field updates (every change lands in the audit trail
             automatically; history readable at /crm/records/{table}/{id}/history)
  • DELETE — SOFT delete (is_active=False) so nothing is ever silently lost;
             restore by PATCHing is_active=true
  • Bulk import — JSON rows (the OS parses CSV/Excel client-side) with
             duplicate detection; orgs deduped by canonical_name, people by
             primary_email then (full_name, org)
  • Export — CSV download for both entities
  • Vendors — the ecosystem view: orgs appearing as vendor_of/subsidiary_of
             edges in org_relationships + VendorIntelligence records
"""
from __future__ import annotations
import csv
import io
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from database import get_db
import models

router = APIRouter(tags=["master-data"])

_ORG_FIELDS = {"canonical_name", "name_ar", "short_name", "country", "region",
               "website", "headquarters", "core_banking", "crm", "payments",
               "cloud", "ai_initiatives", "employee_count", "parent_org_id",
               "is_active", "verification_status"}
_PERSON_FIELDS = {"full_name", "full_name_ar", "current_title", "department",
                  "seniority_level", "primary_email", "phone", "mobile",
                  "whatsapp", "linkedin_url", "country", "city", "tier",
                  "warmness", "persona", "next_step", "background_notes",
                  "is_active", "current_org_id", "do_not_contact",
                  # BD intelligence fields (legacy-dashboard parity)
                  "priority_tier", "priority_score", "is_indian_origin",
                  "is_decision_maker", "is_influencer", "is_connector",
                  "pitch_notes", "bd_priority", "bd_flow_column"}


class UpdateReq(BaseModel):
    fields: dict


# ── organizations (banks) ────────────────────────────────────
@router.patch("/organizations/{org_id}")
def update_org(org_id: str, req: UpdateReq, db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    bad = set(req.fields) - _ORG_FIELDS
    if bad:
        raise HTTPException(status_code=422, detail=f"fields not editable: {sorted(bad)}")
    for k, v in req.fields.items():
        setattr(org, k, v)
    db.commit()
    return {"id": org.id, "updated": sorted(req.fields.keys())}


@router.delete("/organizations/{org_id}")
def delete_org(org_id: str, db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    org.is_active = False          # SOFT delete — audit-trailed, restorable
    db.commit()
    return {"id": org_id, "deleted": "soft", "restore": "PATCH is_active=true"}


class OrgRows(BaseModel):
    rows: list[dict]


@router.post("/import/organizations")
def import_orgs(req: OrgRows, db: Session = Depends(get_db)):
    created = skipped = errors = 0
    seen: set[str] = set()                 # in-batch dedup
    for row in req.rows[:2000]:
        name = (row.get("canonical_name") or row.get("name") or "").strip()
        if not name:
            errors += 1
            continue
        if name.lower() in seen or db.query(models.Organization).filter(
                models.Organization.canonical_name.ilike(name)).first():
            skipped += 1
            continue
        seen.add(name.lower())
        fields = {k: v for k, v in row.items() if k in _ORG_FIELDS}
        fields["canonical_name"] = name
        db.add(models.Organization(**fields))
        created += 1
    db.commit()
    return {"created": created, "skipped_duplicates": skipped, "errors": errors}


@router.get("/export/organizations", response_class=PlainTextResponse)
def export_orgs(db: Session = Depends(get_db)):
    cols = ["id", "canonical_name", "name_ar", "country", "website",
            "core_banking", "employee_count", "is_active"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for o in db.query(models.Organization).all():
        w.writerow([getattr(o, c, "") for c in cols])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=banks.csv"})


# ── persons (contacts) ───────────────────────────────────────
@router.patch("/persons/{person_id}")
def update_person(person_id: str, req: UpdateReq, db: Session = Depends(get_db)):
    p = db.get(models.Person, person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="person not found")
    bad = set(req.fields) - _PERSON_FIELDS
    if bad:
        raise HTTPException(status_code=422, detail=f"fields not editable: {sorted(bad)}")
    for k, v in req.fields.items():
        setattr(p, k, v)
    db.commit()
    return {"id": p.id, "updated": sorted(req.fields.keys())}


@router.delete("/persons/{person_id}")
def delete_person(person_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Person, person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="person not found")
    p.is_active = False
    db.commit()
    return {"id": person_id, "deleted": "soft", "restore": "PATCH is_active=true"}


class PersonRows(BaseModel):
    rows: list[dict]
    org_name: Optional[str] = None      # default org for all rows


@router.post("/import/persons")
def import_persons(req: PersonRows, db: Session = Depends(get_db)):
    created = skipped = errors = 0

    def org_id_for(name: str | None):
        if not name:
            return None
        org = db.query(models.Organization).filter(
            models.Organization.canonical_name.ilike(name.strip())).first()
        if org is None:
            org = models.Organization(canonical_name=name.strip())
            db.add(org)
            db.flush()
        return org.id

    default_org = org_id_for(req.org_name)
    seen_emails: set[str] = set()          # in-batch dedup (session has autoflush off)
    seen_names: set[tuple] = set()
    for row in req.rows[:5000]:
        name = (row.get("full_name") or row.get("name") or "").strip()
        if not name:
            errors += 1
            continue
        email = (row.get("primary_email") or row.get("email") or "").strip() or None
        oid = org_id_for(row.get("org_name") or row.get("bank")) or default_org
        dup = None
        if email:
            dup = (email.lower() in seen_emails
                   or db.query(models.Person).filter_by(primary_email=email).first())
        if not dup:
            key = (name.lower(), oid)
            q = db.query(models.Person).filter(models.Person.full_name.ilike(name))
            if oid:
                q = q.filter(models.Person.current_org_id == oid)
            dup = key in seen_names or q.first()
        if dup:
            skipped += 1
            continue
        if email:
            seen_emails.add(email.lower())
        seen_names.add((name.lower(), oid))
        fields = {k: v for k, v in row.items() if k in _PERSON_FIELDS}
        fields.update({"full_name": name, "primary_email": email,
                       "current_org_id": oid, "is_active": True})
        db.add(models.Person(**fields))
        created += 1
    db.commit()
    return {"created": created, "skipped_duplicates": skipped, "errors": errors}


@router.get("/export/persons", response_class=PlainTextResponse)
def export_persons(org_id: Optional[str] = None, tier: Optional[str] = None,
                   indian: Optional[str] = None, seniority: Optional[str] = None,
                   q: Optional[str] = None, db: Session = Depends(get_db)):
    """Scoped export: all contacts, one bank's, a priority tier, Indian-origin
    only, a seniority level, or a text match — combinable."""
    query = db.query(models.Person)
    if org_id:
        query = query.filter(models.Person.current_org_id == org_id)
    if tier:
        query = query.filter(models.Person.priority_tier == tier)
    if indian == "1":
        query = query.filter(models.Person.is_indian_origin == True)  # noqa: E712
    if seniority:
        query = query.filter(models.Person.seniority_level == seniority)
    if q:
        from sqlalchemy import or_ as _or
        query = query.filter(_or(models.Person.full_name.ilike(f"%{q}%"),
                                 models.Person.current_title.ilike(f"%{q}%")))
    org_name = {o.id: o.canonical_name for o in db.query(models.Organization).all()}
    cols = ["full_name", "current_title", "seniority_level", "priority_tier",
            "is_indian_origin", "primary_email", "phone", "mobile", "linkedin_url",
            "next_step", "last_activity_summary", "is_active"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["bank"] + cols)
    for p in query.all():
        w.writerow([org_name.get(p.current_org_id, "")] +
                   [getattr(p, c, "") for c in cols])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=contacts.csv"})


# ── per-bank vendor management ───────────────────────────────
class VendorAddReq(BaseModel):
    vendor_name: str
    relationship_type: str = "vendor_of"     # vendor_of | subsidiary_of | partner_of
    confidence: float = 0.8
    context: Optional[str] = None
    products: Optional[str] = None


@router.get("/organizations/{org_id}/vendors")
def bank_vendors(org_id: str, db: Session = Depends(get_db)):
    """Vendors/subsidiaries/partners attached to ONE bank."""
    org_name = {o.id: o.canonical_name for o in db.query(models.Organization).all()}
    out = []
    for r in (db.query(models.OrgRelationship)
              .filter(models.OrgRelationship.to_org_id == org_id).all()):
        vi = db.query(models.VendorIntelligence).filter_by(org_id=r.from_org_id).first()
        out.append({"rel_id": r.id, "vendor_org_id": r.from_org_id,
                    "name": org_name.get(r.from_org_id, "?"),
                    "type": r.relationship_type, "confidence": r.confidence,
                    "context": r.context,
                    "products": vi.products if vi else None})
    return out


@router.post("/organizations/{org_id}/vendors", status_code=201)
def add_bank_vendor(org_id: str, req: VendorAddReq, db: Session = Depends(get_db)):
    """Attach a vendor/subsidiary/partner to a bank. Creates the vendor org if
    new; upserts the relationship edge; optional VendorIntelligence products."""
    if db.get(models.Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="bank not found")
    if req.relationship_type not in ("vendor_of", "subsidiary_of", "partner_of"):
        raise HTTPException(status_code=422, detail="relationship_type must be vendor_of|subsidiary_of|partner_of")
    name = req.vendor_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="vendor_name required")
    vend = db.query(models.Organization).filter(
        models.Organization.canonical_name.ilike(name)).first()
    if vend is None:
        vend = models.Organization(canonical_name=name)
        db.add(vend); db.flush()
    rel = (db.query(models.OrgRelationship)
           .filter_by(from_org_id=vend.id, to_org_id=org_id,
                      relationship_type=req.relationship_type).first())
    if rel is None:
        rel = models.OrgRelationship(from_org_id=vend.id, to_org_id=org_id,
                                     relationship_type=req.relationship_type,
                                     confidence=req.confidence, context=req.context,
                                     source="os-ui")
        db.add(rel)
    else:
        rel.confidence = req.confidence
        if req.context:
            rel.context = req.context
    if req.products:
        vi = db.query(models.VendorIntelligence).filter_by(org_id=vend.id).first()
        if vi is None:
            db.add(models.VendorIntelligence(org_id=vend.id, products=req.products))
        else:
            vi.products = req.products
    db.commit()
    return {"vendor_org_id": vend.id, "name": vend.canonical_name,
            "type": req.relationship_type, "attached_to": org_id}


@router.delete("/organizations/{org_id}/vendors/{rel_id}")
def remove_bank_vendor(org_id: str, rel_id: str, db: Session = Depends(get_db)):
    rel = db.get(models.OrgRelationship, rel_id)
    if rel is None or rel.to_org_id != org_id:
        raise HTTPException(status_code=404, detail="relationship not found")
    db.delete(rel); db.commit()      # removes the edge only, never the vendor org
    return {"removed": rel_id}


# ── vendor / subsidiary ecosystem ────────────────────────────
@router.get("/abm/vendors")
def vendors(db: Session = Depends(get_db)):
    """Every org that appears as a vendor/subsidiary/partner of another org,
    with its edges and VendorIntelligence when present."""
    rels = db.query(models.OrgRelationship).all() if hasattr(models, "OrgRelationship") else []
    org_name = {o.id: o.canonical_name for o in db.query(models.Organization).all()}
    by_vendor: dict[str, dict] = {}
    for r in rels:
        if (r.relationship_type or "") not in ("vendor_of", "subsidiary_of", "partner_of"):
            continue
        v = by_vendor.setdefault(r.from_org_id, {
            "org_id": r.from_org_id, "name": org_name.get(r.from_org_id, "?"),
            "edges": []})
        v["edges"].append({"type": r.relationship_type,
                           "to": org_name.get(r.to_org_id, "?"),
                           "confidence": r.confidence, "context": r.context})
    # attach vendor intelligence
    for vi in db.query(models.VendorIntelligence).all():
        v = by_vendor.setdefault(vi.org_id, {
            "org_id": vi.org_id, "name": org_name.get(vi.org_id, "?"), "edges": []})
        v["intelligence"] = {"products": vi.products, "capabilities": vi.capabilities,
                             "clients": vi.clients, "technologies": vi.technologies}
    return sorted(by_vendor.values(), key=lambda x: x["name"] or "")
