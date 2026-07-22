"""add Module 01/02 intelligence-layer tables: signal_clusters,
intelligence_records, hypotheses, nba_recommendations, evidence_refs

Additive: five new tables + tenant RLS/grants (Postgres only). See
models_intel.py's module docstring and
transformation/AI_Intelligence_Layer_Architecture.md section 5.2/Phase 7
for the design this implements (Sprint 3 — Bank Intelligence Agent's
storage dependency).

Revision ID: r5d7e9f1a3b4
Revises: q4c6d8e0f2a3
Create Date: 2026-07-21 19:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'r5d7e9f1a3b4'
down_revision = 'q4c6d8e0f2a3'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models  # noqa: F401
    import models_intel as mi
    return [
        mi.SignalCluster.__table__,
        mi.IntelligenceRecord.__table__,
        mi.Hypothesis.__table__,
        mi.NbaRecommendation.__table__,
        mi.EvidenceRef.__table__,
    ]


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
            if "tenant_id" not in t.c:
                continue
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
