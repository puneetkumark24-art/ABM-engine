"""add Final wave tables: meetings, preference_profiles

Additive: two new tables + tenant RLS/grants (Postgres only).

Revision ID: p3b5c7d9e1f2
Revises: o2a4b6c8e0f1
Create Date: 2026-07-18 16:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'p3b5c7d9e1f2'
down_revision = 'o2a4b6c8e0f1'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models  # noqa: F401
    import models_final
    return [models_final.Meeting.__table__, models_final.PreferenceProfile.__table__]


def upgrade():
    bind = op.get_bind()
    tbls = _tables()
    for t in tbls:
        t.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        BOOT = "00000000-0000-0000-0000-000000000001"
        guc = (f"COALESCE(nullif(current_setting('app.current_tenant', true),'')::uuid, "
               f"'{BOOT}'::uuid)")
        pol = ("coalesce(current_setting('app.current_tenant', true), '') = '' "
               "OR tenant_id::text = current_setting('app.current_tenant', true)")
        for t in tbls:
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
    bind = op.get_bind()
    for t in reversed(_tables()):
        t.drop(bind=bind, checkfirst=True)
