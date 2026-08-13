"""add indexed provider message correlation to send requests

Revision ID: u8c0e2f4a6b8
Revises: t7f9a1b3c5d6
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

revision = "u8c0e2f4a6b8"
# Rebased onto u8a0b2c4d6e7 (the email-event indexes merged earlier today).
# As packaged this revised t7f9a1b3c5d6 directly, which would have produced TWO
# alembic heads and made `upgrade head` ambiguous.
down_revision = "u8a0b2c4d6e7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("send_requests")}
    if "provider_message_id" not in columns:
        op.add_column("send_requests", sa.Column("provider_message_id", sa.String(255), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("send_requests")}
    if "idx_send_provider_message" not in indexes:
        op.create_index("idx_send_provider_message", "send_requests",
                        ["transport", "provider_message_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("send_requests")}
    if "idx_send_provider_message" in indexes:
        op.drop_index("idx_send_provider_message", table_name="send_requests")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("send_requests")}
    if "provider_message_id" in columns:
        op.drop_column("send_requests", "provider_message_id")
