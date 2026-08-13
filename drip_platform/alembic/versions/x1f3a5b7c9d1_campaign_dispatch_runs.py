"""durable batched campaign dispatch runs

Revision ID: x1f3a5b7c9d1
Revises: w0e2f4a6b8d0
"""
from alembic import op
import sqlalchemy as sa

revision = "x1f3a5b7c9d1"
down_revision = "w0e2f4a6b8d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaign_dispatch_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey("email_campaigns.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("transport", sa.String(), nullable=False, server_default="dry_run"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("held_for_human", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("existing_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_error", sa.Text()), sa.Column("created_at", sa.DateTime()),
        sa.Column("started_at", sa.DateTime()), sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("idx_dispatch_run_campaign", "campaign_dispatch_runs", ["campaign_id", "created_at"])
    op.create_table(
        "campaign_dispatch_recipients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("campaign_dispatch_runs.id"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String()), sa.Column("processed_at", sa.DateTime()),
        sa.UniqueConstraint("run_id", "person_id"),
    )
    op.create_index("idx_dispatch_recipient_claim", "campaign_dispatch_recipients",
                    ["run_id", "status", "position"])


def downgrade():
    op.drop_index("idx_dispatch_recipient_claim", table_name="campaign_dispatch_recipients")
    op.drop_table("campaign_dispatch_recipients")
    op.drop_index("idx_dispatch_run_campaign", table_name="campaign_dispatch_runs")
    op.drop_table("campaign_dispatch_runs")
