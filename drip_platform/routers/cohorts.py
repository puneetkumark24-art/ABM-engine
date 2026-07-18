"""routers/cohorts.py — Sprint 7: cohort retention + time-series trend endpoints
over metric_events. Mounted under /analytics."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import cohorts

router = APIRouter(prefix="/analytics", tags=["analytics-cohorts"])


@router.get("/timeseries")
def timeseries(event_type: str, since_days: int = 30, bucket_days: int = 1,
               db: Session = Depends(get_db)):
    return cohorts.timeseries(db, event_type, since_days, bucket_days)


@router.get("/cohort-retention")
def cohort_retention(cohort_event: str, return_event: str, period_days: int = 7,
                     periods: int = 4, since_days: int = 90,
                     db: Session = Depends(get_db)):
    return cohorts.cohort_retention(db, cohort_event, return_event, period_days,
                                    periods, since_days)
