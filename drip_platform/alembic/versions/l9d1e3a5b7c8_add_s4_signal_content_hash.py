"""add Sprint 4 signals.content_hash for idempotent signal collectors

Additive: one nullable column + index on signals. No data migration required
(existing rows keep NULL; new ingests populate the hash).

Revision ID: l9d1e3a5b7c8
Revises: k8c0e2f4a6b7
Create Date: 2026-07-18 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'l9d1e3a5b7c8'
down_revision = 'k8c0e2f4a6b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("signals")]
    if "content_hash" not in cols:
        op.add_column("signals", sa.Column("content_hash", sa.String(64), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS idx_signals_hash ON signals (content_hash)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_signals_hash")
    op.drop_column("signals", "content_hash")
