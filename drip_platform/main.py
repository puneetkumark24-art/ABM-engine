"""
main.py — DRIP FastAPI application (Phase 4: REST API Layer).

Run (dev, SQLite):   uvicorn main:app --reload
Run (prod, Postgres): DATABASE_URL=postgresql+psycopg2://... uvicorn main:app --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI
from database import Base, engine
from routers import organizations, persons, signals, opportunities

app = FastAPI(
    title="DRIP — Decimal Relationship Intelligence Platform",
    version="0.1.0-phase2-6-vertical-slice",
    description="Organization, People, Signal, and Opportunity intelligence API.",
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(organizations.router)
app.include_router(persons.router)
app.include_router(signals.router)
app.include_router(opportunities.router)
