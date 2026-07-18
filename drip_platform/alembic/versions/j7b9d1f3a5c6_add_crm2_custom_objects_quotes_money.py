"""add CRM2: custom objects, products/price-books/quotes, money on opportunities (Sprint 2)

Additive. New CRM2 tables from models_crm2, plus amount_minor(bigint)+currency
on opportunities (money-correct), backfilled from the legacy free-text
estimated_value.

Revision ID: j7b9d1f3a5c6
Revises: i6a8c0e2f4d5
Create Date: 2026-07-18 09:00:00.000000
"""
import os
import re
import sys
from alembic import op
import sqlalchemy as sa

revision = 'j7b9d1f3a5c6'
down_revision = 'i6a8c0e2f4d5'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_NUM = re.compile(r"[\d.]+")


def _to_minor(txt):
    if not txt:
        return None
    t = str(txt).lower().replace(",", "")
    m = _NUM.search(t)
    if not m:
        return None
    val = float(m.group())
    if "m" in t or "million" in t:
        val *= 1_000_000
    elif "k" in t:
        val *= 1_000
    return int(round(val * 100))   # minor units


def _tables():
    import models  # noqa: F401
    import models_crm2
    return [t.__table__ for t in models_crm2.CRM2_TABLES]


def upgrade():
    bind = op.get_bind()
    for t in _tables():
        t.create(bind=bind, checkfirst=True)

    # money-correct column on opportunities (currency already exists; add
    # amount_minor and backfill from the legacy free-text estimated_value).
    op.add_column('opportunities', sa.Column('amount_minor', sa.BigInteger(), nullable=True))
    rows = bind.execute(sa.text(
        "SELECT id, estimated_value FROM opportunities WHERE estimated_value IS NOT NULL")).fetchall()
    for oid, ev in rows:
        minor = _to_minor(ev)
        if minor is not None:
            bind.execute(sa.text("UPDATE opportunities SET amount_minor=:m WHERE id=:i"),
                         {"m": minor, "i": oid})

    # tenant defaults + RLS for the new tables (Postgres only)
    if bind.dialect.name == "postgresql":
        BOOT = "00000000-0000-0000-0000-000000000001"
        guc = (f"COALESCE(nullif(current_setting('app.current_tenant', true),'')::uuid, "
               f"'{BOOT}'::uuid)")
        pol = ("coalesce(current_setting('app.current_tenant', true), '') = '' "
               "OR tenant_id::text = current_setting('app.current_tenant', true)")
        for t in _tables():
            name = t.name
            op.execute(f"ALTER TABLE {name} ADD COLUMN IF NOT EXISTS tenant_id uuid DEFAULT {guc}")
            op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {name}")
            op.execute(f"CREATE POLICY tenant_isolation ON {name} USING ({pol})")
            op.execute(f"CREATE INDEX IF NOT EXISTS idx_{name}_tenant ON {name} (tenant_id)")
            op.execute(
                f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
                f"THEN GRANT SELECT,INSERT,UPDATE,DELETE ON {name} TO app_rw; END IF; END $$;")


def downgrade():
    bind = op.get_bind()
    op.drop_column('opportunities', 'amount_minor')
    for t in reversed(_tables()):
        t.drop(bind=bind, checkfirst=True)
