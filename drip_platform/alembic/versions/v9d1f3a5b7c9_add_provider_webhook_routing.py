"""add PII-free provider webhook tenant routing directory

Revision ID: v9d1f3a5b7c9
Revises: u8c0e2f4a6b8
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

revision = "v9d1f3a5b7c9"
down_revision = "u8c0e2f4a6b8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "provider_message_maps" in sa.inspect(bind).get_table_names():
        return
    op.create_table("provider_message_maps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("message_id", sa.String(80), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", "provider_message_id", name="uq_provider_message_map"))
    op.create_index("idx_provider_map_message", "provider_message_maps",
                    ["tenant_id", "message_id"])


def downgrade():
    op.drop_index("idx_provider_map_message", table_name="provider_message_maps")
    op.drop_table("provider_message_maps")
