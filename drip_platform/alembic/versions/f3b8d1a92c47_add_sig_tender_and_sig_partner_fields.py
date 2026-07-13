"""add SIG-TENDER and SIG-PARTNER fields to signals

Revision ID: f3b8d1a92c47
Revises: a9c3e7f21b58
Create Date: 2026-07-13 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3b8d1a92c47'
down_revision = 'a9c3e7f21b58'
branch_labels = None
depends_on = None


def upgrade():
    # SIG-TENDER (OPEN-GAP-SIG-02) — manual RFP/tender input fields
    op.add_column('signals', sa.Column('deadline', sa.DateTime(), nullable=True))
    op.add_column('signals', sa.Column('estimated_value', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('scope_description', sa.Text(), nullable=True))
    op.add_column('signals', sa.Column('contact_person', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('source_of_knowledge', sa.String(), nullable=True))
    # SIG-PARTNER (OPEN-GAP-SIG-06) — competitive/complementary classification
    op.add_column('signals', sa.Column('partner_classification', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('partner_classification_matched_vendor', sa.String(), nullable=True))


def downgrade():
    op.drop_column('signals', 'partner_classification_matched_vendor')
    op.drop_column('signals', 'partner_classification')
    op.drop_column('signals', 'source_of_knowledge')
    op.drop_column('signals', 'contact_person')
    op.drop_column('signals', 'scope_description')
    op.drop_column('signals', 'estimated_value')
    op.drop_column('signals', 'deadline')
