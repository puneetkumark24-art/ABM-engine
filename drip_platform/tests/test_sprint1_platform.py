"""
Sprint 1 test — observability (health/ready/metrics + request-id), route-level
authorization enforcement, and the universal audit trail (before/after).
Runs on SQLite and PostgreSQL.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    from database import Base, engine, SessionLocal
    import models, models_ext, models_p10, models_p11, models_p12, models_audit as ma  # noqa
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)

    # ── OBSERVABILITY ──
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import observability
    from tenant_middleware import TenantMiddleware
    from auth import issue_token

    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    observability.setup_logging()
    observability.register(app, engine)

    @app.get("/crm/thing")
    def crm_thing():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/health/live")
    check("OBS /health/live 200", r.status_code == 200 and r.json()["status"] == "alive")
    rr = client.get("/health/ready")
    check("OBS /health/ready reports db ok", rr.status_code == 200 and rr.json()["db"] == "ok")
    rid = client.get("/health/live").headers.get("x-request-id")
    check("OBS response carries x-request-id", bool(rid))
    m = client.get("/metrics")
    check("OBS /metrics prometheus text", "drip_requests_total" in m.text and m.status_code == 200)
    check("OBS metrics count requests", "drip_request_latency_seconds_count" in m.text)

    # ── AUTHORIZATION (route-level) ──
    os.environ["AUTH_ENFORCED"] = "true"
    import importlib, tenant_middleware
    importlib.reload(tenant_middleware)
    app2 = FastAPI()
    app2.add_middleware(tenant_middleware.TenantMiddleware)

    @app2.get("/crm/thing")
    def t2():
        return {"ok": True}

    @app2.get("/health/live")
    def h2():
        return {"status": "alive"}
    c2 = TestClient(app2)
    tok_noscope = issue_token("u", "t1", scopes=["marketing.manage"])
    tok_crm = issue_token("u", "t1", scopes=["crm.read"])
    check("AUTHZ no token on protected -> 401", c2.get("/crm/thing").status_code == 401)
    check("AUTHZ wrong scope -> 403",
          c2.get("/crm/thing", headers={"Authorization": f"Bearer {tok_noscope}"}).status_code == 403)
    check("AUTHZ correct scope -> 200",
          c2.get("/crm/thing", headers={"Authorization": f"Bearer {tok_crm}"}).status_code == 200)
    check("AUTHZ public path exempt", c2.get("/health/live").status_code == 200)
    os.environ["AUTH_ENFORCED"] = "false"
    importlib.reload(tenant_middleware)

    # ── UNIVERSAL AUDIT TRAIL ──
    import audit_trail
    audit_trail.register()
    db = SessionLocal()
    org = models.Organization(canonical_name="Audit Bank")
    db.add(org); db.commit()
    ins = db.query(ma.AuditEvent).filter_by(table_name="organizations", action="insert").all()
    check("AUDIT insert recorded with after-values",
          any(e.after and e.after.get("canonical_name") == "Audit Bank" for e in ins))

    org.canonical_name = "Audit Bank Renamed"
    org.website = "https://x.invalid"
    db.commit()
    upd = db.query(ma.AuditEvent).filter_by(table_name="organizations", action="update").all()
    e = upd[-1] if upd else None
    check("AUDIT update records before+after+changed",
          e is not None and e.before.get("canonical_name") == "Audit Bank"
          and e.after.get("canonical_name") == "Audit Bank Renamed"
          and "canonical_name" in (e.changed or []))
    check("AUDIT update captured second changed field", e is not None and "website" in (e.changed or []))

    db.delete(org); db.commit()
    dele = db.query(ma.AuditEvent).filter_by(table_name="organizations", action="delete").count()
    check("AUDIT delete recorded", dele >= 1)

    # high-volume event tables are NOT audited (no amplification)
    db.add(models_ext.MetricEvent(event_type="noise")); db.commit()
    check("AUDIT excludes high-volume event tables",
          db.query(ma.AuditEvent).filter_by(table_name="metric_events").count() == 0)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_sprint1_platform():
    assert run()
