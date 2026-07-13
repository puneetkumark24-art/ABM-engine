"""add EPIS confidence/decay fields to signals (Signal Pipeline P1)

Revision ID: b1e4a9c07d32
Revises: f3b8d1a92c47
Create Date: 2026-07-13 18:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1e4a9c07d32'
down_revision = 'f3b8d1a92c47'
branch_labels = None
depends_on = None


def upgrade():
    # Signal Pipeline P1 (EPIS-RCM-01, EPIS-HALF-01) — see etl/signal_decay.py and
    # docs/Signal_Pipeline_Architecture.md §4.1. All nullable/additive; existing rows
    # are untouched until the backfill script runs.
    op.add_column('signals', sa.Column('confidence_score', sa.Float(), nullable=True))
    op.add_column('signals', sa.Column('decay_category', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('decay_expires_at', sa.DateTime(), nullable=True))
    op.add_column('signals', sa.Column('source_reliability', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('signals', 'source_reliability')
    op.drop_column('signals', 'decay_expires_at')
    op.drop_column('signals', 'decay_category')
    op.drop_column('signals', 'confidence_score')
