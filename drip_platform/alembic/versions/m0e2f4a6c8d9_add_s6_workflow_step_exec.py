"""add Sprint 6 workflow_step_executions (durable retry/idempotency ledger)

Additive: one new table + tenant RLS/grants (Postgres only). No existing table
touched.

Revision ID: m0e2f4a6c8d9
Revises: l9d1e3a5b7c8
Create Date: 2026-07-18 12:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'm0e2f4a6c8d9'
down_revision = 'l9d1e3a5b7c8'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _table():
    import models  # noqa: F401
    import models_s6
    return models_s6.WorkflowStepExecution.__table__


def upgrade():
    bind = op.get_bind()
    t = _table()
    t.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        BOOT = "00000000-0000-0000-0000-000000000001"
        guc = (f"COALESCE(nullif(current_setting('app.current_tenant', true),'')::uuid, "
               f"'{BOOT}'::uuid)")
        pol = ("coalesce(current_setting('app.current_tenant', true), '') = '' "
               "OR tenant_id::text = current_setting('app.current_tenant', true)")
        n = t.name
        op.execute(f"ALTER TABLE {n} ALTER COLUMN tenant_id SET DEFAULT {guc}")
        op.execute(f"ALTER TABLE {n} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {n} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {n}")
        op.execute(f"CREATE POLICY tenant_isolation ON {n} USING ({pol})")
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
            f"THEN GRANT SELECT,INSERT,UPDATE,DELETE ON {n} TO app_rw; END IF; END $$;")


def downgrade():
    _table().drop(bind=op.get_bind(), checkfirst=True)
