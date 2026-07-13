from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from database import get_db
import models, schemas

router = APIRouter(prefix="/persons", tags=["persons"])


@router.get("", response_model=List[schemas.PersonOut])
def list_persons(
    search: Optional[str] = None,
    tier: Optional[str] = None,
    org_id: Optional[str] = None,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(models.Person).filter(models.Person.is_active == True)  # noqa: E712
    if search:
        q = q.filter(or_(models.Person.full_name.ilike(f"%{search}%"),
                          models.Person.current_title.ilike(f"%{search}%")))
    if tier:
        q = q.filter(models.Person.tier == tier)
    if org_id:
        q = q.filter(models.Person.current_org_id == org_id)
    return q.order_by(models.Person.priority_score.desc()).limit(limit).all()


@router.get("/{person_id}", response_model=schemas.PersonOut)
def get_person(person_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Person, person_id)
    if not p:
        raise HTTPException(404, "Person not found")
    return p


@router.post("", response_model=schemas.PersonOut, status_code=201)
def create_person(payload: schemas.PersonCreate, db: Session = Depends(get_db)):
    person = models.Person(**payload.model_dump())
    db.add(person)
    db.commit()
    db.refresh(person)
    return person
