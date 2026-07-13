from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from database import get_db
import models, schemas

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=List[schemas.SignalOut])
def list_signals(
    urgency: Optional[str] = None,
    unread_only: bool = False,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(models.Signal)
    if urgency:
        q = q.filter(models.Signal.urgency == urgency)
    if unread_only:
        q = q.filter(models.Signal.is_read == False)  # noqa: E712
    return q.order_by(models.Signal.created_at.desc()).limit(limit).all()
