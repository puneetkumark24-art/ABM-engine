"""widen message_id columns to VARCHAR(80)

Found by running the suite on real PostgreSQL: composite message ids
("seq-<uuid>-<step>", "wf-<uuid>-<node>") exceed VARCHAR(36). SQLite ignores
VARCHAR lengths so this never surfaced there. Postgres-only ALTER; SQLite
databases created from the (already-corrected) models need nothing.

Revision ID: a7c4e2f1d8b3
Revises: f0a3d6e9c1b7
Create Date: 2026-07-16 19:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7c4e2f1d8b3'
down_revision = 'f0a3d6e9c1b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column('send_requests', 'message_id', type_=sa.String(80))
        op.alter_column('delivery_events', 'message_id', type_=sa.String(80))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column('delivery_events', 'message_id', type_=sa.String(36))
        op.alter_column('send_requests', 'message_id', type_=sa.String(36))
