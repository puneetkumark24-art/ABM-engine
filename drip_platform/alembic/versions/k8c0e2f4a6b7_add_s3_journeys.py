"""add Sprint 3 marketing journey orchestration (journey_defs, journey_enrollments)

Additive. Two new tables from models_s3, tenant-scoped with RLS + grants
(Postgres only), mirroring the CRM2 migration pattern. No existing table touched.

Revision ID: k8c0e2f4a6b7
Revises: j7b9d1f3a5c6
Create Date: 2026-07-18 10:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'k8c0e2f4a6b7'
down_revision = 'j7b9d1f3a5c6'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models  # noqa: F401
    import models_s3
    return [models_s3.JourneyDef.__table__, models_s3.JourneyEnrollment.__table__]


def _apply_rls(bind, names):
    if bind.dialect.name != "postgresql":
        return
    BOOT = "00000000-0000-0000-0000-000000000001"
    guc = (f"COALESCE(nullif(current_setting('app.current_tenant', true),'')::uuid, "
           f"'{BOOT}'::uuid)")
    pol = ("coalesce(current_setting('app.current_tenant', true), '') = '' "
           "OR tenant_id::text = current_setting('app.current_tenant', true)")
    for name in names:
        op.execute(f"ALTER TABLE {name} ALTER COLUMN tenant_id SET DEFAULT {guc}")
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {name}")
        op.execute(f"CREATE POLICY tenant_isolation ON {name} USING ({pol})")
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
            f"THEN GRANT SELECT,INSERT,UPDATE,DELETE ON {name} TO app_rw; END IF; END $$;")


def upgrade():
    bind = op.get_bind()
    tbls = _tables()
    for t in tbls:
        t.create(bind=bind, checkfirst=True)
    _apply_rls(bind, [t.name for t in tbls])


def downgrade():
    bind = op.get_bind()
    for t in reversed(_tables()):
        t.drop(bind=bind, checkfirst=True)
