"""add signal_v2_exports table -- audit ledger for the Signal Engine v2
integration (idempotent export tracking, shadow-mode).

Additive only. Does not touch `signals`, `organizations`, or any existing
table -- the export target (`signals`) already has every column this bridge
needs (org_id, signal_type, source, title, summary, url, urgency,
confidence_score, content_hash). This migration adds ONLY the ledger that
records which signal_engine UUIDs have already been exported, so re-running
the export script is idempotent and auditable.

See abm_platform/services/signal_v2_bridge.py and
scripts/signal_v2_export_cli.py.

Rollback: downgrade() drops signal_v2_exports only. No data in `signals` is
touched by rollback -- any signals already exported before a rollback remain
in place; only the ledger tracking them is removed, so a re-export after a
future re-upgrade would (harmlessly) attempt to re-insert already-present
rows, which the bridge's own preview() step would need to re-dedupe against
`signals.content_hash` in that edge case.

Revision ID: s6e8f0a2c4d5
Revises: r5d7e9f1a3b4
Create Date: 2026-08-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 's6e8f0a2c4d5'
down_revision = 'r5d7e9f1a3b4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.create_table(
        "signal_v2_exports",
        sa.Column("signal_uuid", sa.String(64), primary_key=True),
        sa.Column("drip_signal_id", sa.String(36), nullable=False),
        sa.Column("se_account_id", sa.String(64), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("exported_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("export_policy", sa.String(64), nullable=False),
    )
    op.create_index("idx_signal_v2_exports_org", "signal_v2_exports", ["org_id"])
    if bind.dialect.name == "postgresql":
        # No tenant_id / RLS on this table -- it holds only export
        # bookkeeping (which signal_engine UUIDs are already exported), not
        # customer-facing content, so per-tenant isolation isn't meaningful
        # here. Grant follows the same app_rw convention as every other
        # migration in this chain (see r5d7e9f1a3b4, q4c6d8e0f2a3).
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
            "THEN GRANT SELECT,INSERT ON signal_v2_exports TO app_rw; END IF; END $$;"
        )


def downgrade():
    op.drop_index("idx_signal_v2_exports_org", table_name="signal_v2_exports")
    op.drop_table("signal_v2_exports")
