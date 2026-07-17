"""
main.py — DRIP FastAPI application (Phase 4: REST API Layer).

Run (dev, SQLite):   uvicorn main:app --reload
Run (prod, Postgres): DATABASE_URL=postgresql+psycopg2://... uvicorn main:app --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI
from database import Base, engine
from routers import organizations, persons, signals, opportunities, sequences, platform_status, platform_modules, engine_e2e, tracking_decision, crm_marketing_ext

app = FastAPI(
    title="DRIP — Decimal Relationship Intelligence Platform",
    version="0.1.0-phase2-6-vertical-slice",
    description="Organization, People, Signal, and Opportunity intelligence API.",
)

# P0-A.2: request-scoped tenancy. Sets the RLS GUC from the JWT so every route
# using Depends(get_db) is automatically tenant-scoped. Enforcement via
# AUTH_ENFORCED env (default off for dev/tests; public /t/*, /p/* exempt).
from tenant_middleware import TenantMiddleware  # noqa: E402
app.add_middleware(TenantMiddleware)


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
app.include_router(sequences.router)
app.include_router(platform_status.router)
app.include_router(platform_modules.router)
app.include_router(engine_e2e.router)
app.include_router(tracking_decision.router)
app.include_router(crm_marketing_ext.router)
