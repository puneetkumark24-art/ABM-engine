"""add document extraction fields to document_uploads

Revision ID: a9c3e7f21b58
Revises: 8a1f2c9d4e6b
Create Date: 2026-07-12 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a9c3e7f21b58'
down_revision = '8a1f2c9d4e6b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('document_uploads', sa.Column('extracted_text', sa.Text(), nullable=True))
    op.add_column('document_uploads', sa.Column('extracted_summary', sa.Text(), nullable=True))
    op.add_column('document_uploads', sa.Column('detected_entities', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('document_uploads', 'detected_entities')
    op.drop_column('document_uploads', 'extracted_summary')
    op.drop_column('document_uploads', 'extracted_text')
