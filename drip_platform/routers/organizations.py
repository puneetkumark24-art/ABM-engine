from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from database import get_db
import models, schemas

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=List[schemas.OrganizationOut])
def list_organizations(
    search: Optional[str] = None,
    type_tag: Optional[str] = None,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(models.Organization).filter(models.Organization.is_active == True)  # noqa: E712
    if search:
        q = q.filter(or_(models.Organization.canonical_name.ilike(f"%{search}%"),
                          models.Organization.short_name.ilike(f"%{search}%")))
    if type_tag:
        q = q.join(models.OrgTypeTag).filter(models.OrgTypeTag.type_tag == type_tag)
    return q.limit(limit).all()


@router.get("/{org_id}", response_model=schemas.OrganizationOut)
def get_organization(org_id: str, db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    return org


@router.get("/{org_id}/account", response_model=schemas.AccountIntelligenceOut)
def get_account_intelligence(org_id: str, db: Session = Depends(get_db)):
    acc = db.get(models.AccountIntelligence, org_id)
    if not acc:
        raise HTTPException(404, "This organization has no sales/account intelligence record")
    return acc


@router.get("/{org_id}/persons", response_model=List[schemas.PersonOut])
def get_organization_persons(org_id: str, db: Session = Depends(get_db)):
    return db.query(models.Person).filter(models.Person.current_org_id == org_id).all()


@router.get("/{org_id}/signals", response_model=List[schemas.SignalOut])
def get_organization_signals(org_id: str, limit: int = 20, db: Session = Depends(get_db)):
    return (db.query(models.Signal).filter(models.Signal.org_id == org_id)
            .order_by(models.Signal.created_at.desc()).limit(limit).all())


@router.post("", response_model=schemas.OrganizationOut, status_code=201)
def create_organization(payload: schemas.OrganizationCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Organization).filter(
        models.Organization.canonical_name == payload.canonical_name).first()
    if existing:
        raise HTTPException(409, "Organization with this name already exists")
    org = models.Organization(**payload.model_dump(exclude={"type_tags"}))
    db.add(org)
    db.flush()
    for tag in payload.type_tags:
        db.add(models.OrgTypeTag(org_id=org.id, type_tag=tag))
    db.commit()
    db.refresh(org)
    return org
