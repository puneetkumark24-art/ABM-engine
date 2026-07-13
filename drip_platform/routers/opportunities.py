from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional, List
from database import get_db
import models, schemas

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=List[schemas.OpportunityOut])
def list_opportunities(stage: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Opportunity)
    if stage:
        q = q.filter(models.Opportunity.stage == stage)
    return q.all()
