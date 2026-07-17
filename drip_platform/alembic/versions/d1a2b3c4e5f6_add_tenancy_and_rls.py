"""add multi-tenancy + Row-Level Security (P0-A)

Non-destructive tenancy pass. POSTGRES ONLY (RLS/roles/GUC are PG features;
SQLite dev/test paths are unaffected and use the ORM models which remain
tenant-agnostic for now).

For every existing table in `public` (except tenants/alembic_version):
  * ADD COLUMN tenant_id uuid DEFAULT <bootstrap>  (fast, fills existing rows)
  * ENABLE + FORCE ROW LEVEL SECURITY
  * CREATE POLICY tenant_isolation:
        USING ( current_setting('app.current_tenant', true) IS NULL
                OR tenant_id::text = current_setting('app.current_tenant', true) )
    (permissive when the GUC is unset — a deliberate gradual-rollout aid so
    pre-tenancy callers keep working; tighten to strict + WITH CHECK once all
    callers set tenant context.)

App connects as non-superuser role `app_rw` (superusers bypass RLS); grants are
applied if that role exists.

Revision ID: d1a2b3c4e5f6
Revises: c9e6a4b8d2f0
Create Date: 2026-07-16 23:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1a2b3c4e5f6'
down_revision = 'c9e6a4b8d2f0'
branch_labels = None
depends_on = None

BOOTSTRAP = "00000000-0000-0000-0000-000000000001"
EXCLUDE = {"tenants", "alembic_version"}


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite/others: tenancy handled at app layer, RLS unavailable

    # 1) tenants table + bootstrap row
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id varchar(36) PRIMARY KEY,
            name varchar NOT NULL UNIQUE,
            slug varchar UNIQUE,
            plan varchar DEFAULT 'standard',
            status varchar DEFAULT 'active',
            settings jsonb DEFAULT '{}'::jsonb,
            is_bootstrap boolean DEFAULT false,
            created_at timestamp DEFAULT now()
        )""")
    op.execute(f"""
        INSERT INTO tenants (id, name, slug, is_bootstrap)
        VALUES ('{BOOTSTRAP}', 'bootstrap', 'bootstrap', true)
        ON CONFLICT (id) DO NOTHING""")

    # 2) per-table tenant_id + RLS, iterating live tables
    rows = bind.execute(sa.text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'")).fetchall()
    for (table,) in rows:
        if table in EXCLUDE:
            continue
        op.execute(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS '
                   f"tenant_id uuid DEFAULT '{BOOTSTRAP}'::uuid")
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        # coalesce(...,'')='' treats BOTH unset (NULL) and touched-but-cleared
        # ('') GUC as "no tenant context" → permissive (gradual-rollout aid).
        # Postgres returns '' not NULL once a custom GUC has been referenced.
        op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
            USING ( coalesce(current_setting('app.current_tenant', true), '') = ''
                    OR tenant_id::text = current_setting('app.current_tenant', true) )''')
        op.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_tenant" '
                   f'ON "{table}" (tenant_id)')

    # 3) grant to the app role if it exists (ops creates app_rw)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') THEN
            GRANT USAGE ON SCHEMA public TO app_rw;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
          END IF;
        END $$;""")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    import sqlalchemy as sa
    rows = bind.execute(sa.text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'")).fetchall()
    for (table,) in rows:
        if table in EXCLUDE:
            continue
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS tenant_id')
    op.execute("DROP TABLE IF EXISTS tenants")
