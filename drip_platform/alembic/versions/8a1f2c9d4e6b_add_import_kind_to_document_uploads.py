"""add import_kind to document_uploads

Revision ID: 8a1f2c9d4e6b
Revises: 2d87f95e929c
Create Date: 2026-07-11 21:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '8a1f2c9d4e6b'
down_revision = '2d87f95e929c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('document_uploads', sa.Column('import_kind', sa.String(), nullable=True, server_default='contacts'))


def downgrade():
    op.drop_column('document_uploads', 'import_kind')
