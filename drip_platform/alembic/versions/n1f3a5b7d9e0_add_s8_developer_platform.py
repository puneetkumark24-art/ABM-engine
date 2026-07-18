"""add Sprint 8 developer platform (api_keys, webhook_subscriptions, webhook_deliveries)

Additive: three new tables + tenant RLS/grants (Postgres only). No existing
table touched.

Revision ID: n1f3a5b7d9e0
Revises: m0e2f4a6c8d9
Create Date: 2026-07-18 13:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'n1f3a5b7d9e0'
down_revision = 'm0e2f4a6c8d9'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models  # noqa: F401
    import models_s8
    return [models_s8.ApiKey.__table__, models_s8.WebhookSubscription.__table__,
            models_s8.WebhookDelivery.__table__]


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
