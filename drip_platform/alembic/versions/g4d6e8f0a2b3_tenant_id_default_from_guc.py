"""tenant_id default reads the session tenant GUC (P0-A.2)

Makes every tenant_id column default to the CURRENT session tenant
(`app.current_tenant`), falling back to bootstrap when unset. Effect: any INSERT
that omits tenant_id — i.e. every existing ORM insert, unchanged — is stamped
with the tenant of the session that issued it. Combined with the RLS read policy
(Phase 13), the database now enforces tenant isolation on BOTH reads and writes
without touching a single ORM model.

Postgres-only.

Revision ID: g4d6e8f0a2b3
Revises: f3c5a7b9d1e2
Create Date: 2026-07-17 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'g4d6e8f0a2b3'
down_revision = 'f3c5a7b9d1e2'
branch_labels = None
depends_on = None

BOOTSTRAP = "00000000-0000-0000-0000-000000000001"
GUC_DEFAULT = (f"COALESCE("
               f"nullif(current_setting('app.current_tenant', true), '')::uuid, "
               f"'{BOOTSTRAP}'::uuid)")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    cols = bind.execute(sa.text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE column_name='tenant_id' AND table_schema='public'")).fetchall()
    for (table,) in cols:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN tenant_id SET DEFAULT {GUC_DEFAULT}')


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    cols = bind.execute(sa.text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE column_name='tenant_id' AND table_schema='public'")).fetchall()
    for (table,) in cols:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN tenant_id SET DEFAULT '
                   f"'{BOOTSTRAP}'::uuid")
