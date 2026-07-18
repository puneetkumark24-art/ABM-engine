"""
P0-A.2 test — write-side tenancy: an ORM insert under a tenant session is
stamped with that tenant (via the GUC-reading column default), and reads are
isolated. Plus the HTTP middleware: tenant from JWT, public-path exemption,
enforcement toggle.

RLS/write-stamping is Postgres-only (needs the GUC default + RLS). Middleware
checks run everywhere.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import sqlalchemy as sa  # noqa: E402
from auth import issue_token  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


TA = "11111111-1111-1111-1111-111111111111"
TB = "22222222-2222-2222-2222-222222222222"


def run_writes():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("… write-stamping skipped (needs PostgreSQL)"); return
    import database
    from tenancy import tenant_session
    import models

    admin = sa.create_engine(url)
    with admin.begin() as c:
        for tid, nm in [(TA, "WA"), (TB, "WB")]:
            c.execute(sa.text("INSERT INTO tenants (id,name,slug) VALUES (:i,:n,:n) "
                              "ON CONFLICT (id) DO NOTHING"), {"i": tid, "n": nm})
        c.execute(sa.text("DELETE FROM organizations WHERE canonical_name IN "
                          "('WriteOrg A','WriteOrg B')"))

    # insert via the ORM under a tenant-A session — tenant_id omitted by the ORM,
    # filled by the GUC-reading column default.
    with tenant_session(TA) as db:
        db.add(models.Organization(canonical_name="WriteOrg A"))
        db.commit()
    with tenant_session(TB) as db:
        db.add(models.Organization(canonical_name="WriteOrg B"))
        db.commit()

    # verify the stamped tenant_id (as superuser, bypassing RLS to inspect)
    with admin.connect() as c:
        a_tid = c.execute(sa.text("SELECT tenant_id::text FROM organizations "
                                  "WHERE canonical_name='WriteOrg A'")).scalar()
        b_tid = c.execute(sa.text("SELECT tenant_id::text FROM organizations "
                                  "WHERE canonical_name='WriteOrg B'")).scalar()
    check("WRITE ORM insert stamped with session tenant A", a_tid == TA)
    check("WRITE ORM insert stamped with session tenant B", b_tid == TB)
    check("WRITE not stamped as bootstrap", a_tid != "00000000-0000-0000-0000-000000000001")

    # read isolation must be checked as the NON-superuser app role (superusers
    # bypass RLS — the app connects as app_rw in production).
    with admin.begin() as c:
        c.execute(sa.text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
                          "THEN CREATE ROLE app_rw LOGIN NOSUPERUSER; END IF; END $$;"))
        c.execute(sa.text("GRANT USAGE ON SCHEMA public TO app_rw"))
        c.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw"))
    app_eng = sa.create_engine("postgresql+psycopg2://app_rw@" + url.split("@", 1)[1])
    with app_eng.begin() as c:
        c.execute(sa.text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TA})
        names = [r[0] for r in c.execute(sa.text(
            "SELECT canonical_name FROM organizations WHERE canonical_name LIKE 'WriteOrg%'")).fetchall()]
    check("WRITE read isolation (as app_rw): tenant A sees only its org", names == ["WriteOrg A"])


def run_middleware():
    # pin enforcement OFF for the first half regardless of deployment .env
    # (the local-network .env sets AUTH_ENFORCED=true, which dotenv loads)
    os.environ["AUTH_ENFORCED"] = "false"
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import database
    from tenant_middleware import TenantMiddleware

    async def whoami(request):
        return JSONResponse({"tenant": database.current_tenant_var.get()})

    async def public(request):
        return JSONResponse({"tenant": database.current_tenant_var.get(), "public": True})

    app = Starlette(routes=[Route("/whoami", whoami), Route("/t/ping", public),
                            Route("/health", public)])
    app.add_middleware(TenantMiddleware)
    client = TestClient(app)

    # token present -> tenant flows into contextvar
    tok = issue_token("u", TA, scopes=["*"])
    r = client.get("/whoami", headers={"Authorization": f"Bearer {tok}"})
    check("MW token sets tenant context", r.json().get("tenant") == TA)
    # no token, enforcement off -> allowed, tenant None
    r2 = client.get("/whoami")
    check("MW no token (enforcement off) allowed", r2.status_code == 200 and r2.json()["tenant"] is None)
    # public path always allowed
    r3 = client.get("/t/ping")
    check("MW public path exempt", r3.status_code == 200)

    # enforcement ON -> protected path without token = 401, public still ok
    os.environ["AUTH_ENFORCED"] = "true"
    import importlib, tenant_middleware
    importlib.reload(tenant_middleware)
    app2 = Starlette(routes=[Route("/whoami", whoami), Route("/t/ping", public),
                             Route("/health", public)])
    app2.add_middleware(tenant_middleware.TenantMiddleware)
    c2 = TestClient(app2)
    check("MW enforced: protected path 401 without token", c2.get("/whoami").status_code == 401)
    check("MW enforced: valid token passes",
          c2.get("/whoami", headers={"Authorization": f"Bearer {tok}"}).status_code == 200)
    check("MW enforced: public path still open", c2.get("/t/ping").status_code == 200)
    check("MW enforced: bad token 401",
          c2.get("/whoami", headers={"Authorization": "Bearer garbage"}).status_code == 401)
    os.environ["AUTH_ENFORCED"] = "false"
    importlib.reload(tenant_middleware)


def run():
    # SAFETY GUARD: write-path RLS probes belong on a disposable test DB only.
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql") and not os.environ.get("DRIP_ALLOW_PG_TESTS"):
        print("SKIP - PG tenant-write suite guarded: set DRIP_ALLOW_PG_TESTS=1 on a "
              "DISPOSABLE test database (never your production drip DB).")
        run_middleware()
        passed = sum(1 for _, ok in _results if ok); total = len(_results)
        print(f"\n{passed}/{total} checks passed  [DB: guarded — middleware only]")
        return passed == total
    run_writes()
    run_middleware()
    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    db = "postgresql" if os.environ.get("DATABASE_URL", "").startswith("postgresql") else "sqlite"
    print(f"\n{passed}/{total} checks passed  [DB: {db}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_tenant_writes():
    assert run()
