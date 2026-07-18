"""
main.py — DRIP FastAPI application (Phase 4: REST API Layer).

Run (dev, SQLite):   uvicorn main:app --reload
Run (prod, Postgres): DATABASE_URL=postgresql+psycopg2://... uvicorn main:app --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI
from database import Base, engine
from routers import organizations, persons, signals, opportunities, sequences, platform_status, platform_modules, engine_e2e, tracking_decision, crm_marketing_ext, crm2, journeys, abm_intel, sales_engagement, workflow_durable, cohorts, developer_platform, security_compliance, webapp, unified, auth_login, parity, final_wave, os_shell, master_data, bd_parity

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

# U1-deploy: CORS so browser UIs on other origins (the Lovable CRM workspace)
# can call this API once deployed. Origins from CORS_ORIGINS (csv); default
# allows the published CRM + local dev.
import os as _os  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
_default_origins = "https://drip-saudi-abm.lovable.app,http://127.0.0.1:8000,http://localhost:8000"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sprint 1: observability (structured logs + request-id + health/ready/metrics)
# and the universal audit trail (before/after on every business mutation).
import observability  # noqa: E402
import audit_trail  # noqa: E402
observability.setup_logging()
observability.register(app, engine)
audit_trail.register()


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
app.include_router(crm2.router)
app.include_router(journeys.router)
app.include_router(abm_intel.router)
app.include_router(sales_engagement.router)
app.include_router(workflow_durable.router)
app.include_router(cohorts.router)
app.include_router(developer_platform.router)
app.include_router(security_compliance.router)
app.include_router(webapp.router)
app.include_router(unified.router)
app.include_router(auth_login.router)
app.include_router(parity.router)
app.include_router(final_wave.router)
app.include_router(os_shell.router)
app.include_router(master_data.router)
app.include_router(bd_parity.router)
app.include_router(bd_parity.mkt)

# Parity Mission: wire the LLM behind the existing AI seams when a key exists.
# Guardrails (PII anonymization, QC, c-suite human gate) are unchanged — the
# LLM only replaces the offline text generator inside them.
try:
    from abm_platform.services import llm_core as _llm
    if _llm.active_provider():
        from database import SessionLocal as _SL
        _llm.enable_ai(_SL)
except Exception:  # noqa: BLE001 — AI wiring must never block boot
    pass
