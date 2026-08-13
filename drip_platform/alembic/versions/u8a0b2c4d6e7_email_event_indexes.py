"""Indexes for the canonical email-event model.

The Mailchimp-style analytics and the suppression rules query delivery_events
in three shapes that had no supporting index:

  1. "soft bounces for this address in the last 30 days" — the 3-strike
     suppression rule, joined to email_messages on message_id and filtered on
     (event_type, occurred_at). Without an index this is a sequential scan of
     the whole event table on every soft bounce in a batch.
  2. "every event since <date>, optionally for one campaign" — the analytics
     aggregation, filtered on occurred_at.
  3. "messages for this recipient" — email_messages.to_email, used by the
     suppression join above and by the per-recipient campaign view.

delivery_events grows fastest of any table here: one row per recipient per
lifecycle stage, so a single 30,000-recipient campaign can add 150,000+ rows.
These are the indexes that keep it usable at that size.

Idempotent (IF NOT EXISTS) so it is safe on a database where an operator
already added one by hand, and reversible.

Revision ID: u8a0b2c4d6e7
Revises: t7f9a1b3c5d6
Create Date: 2026-08-12 23:30:00.000000
"""
from alembic import op

revision = "u8a0b2c4d6e7"
down_revision = "t7f9a1b3c5d6"
branch_labels = None
depends_on = None

_INDEXES = (
    # (name, table, columns)
    ("idx_dev_type_time", "delivery_events", "event_type, occurred_at"),
    ("idx_dev_occurred", "delivery_events", "occurred_at"),
    ("idx_emsg_to_email", "email_messages", "to_email"),
    ("idx_tracked_link_msg", "tracked_links", "message_id"),
)


def upgrade():
    bind = op.get_bind()
    for name, table, cols in _INDEXES:
        if bind.dialect.name == "postgresql":
            # A partial/plain btree either way; IF NOT EXISTS keeps this safe to
            # re-run against a database that was hand-patched during triage.
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
        else:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")


def downgrade():
    for name, _table, _cols in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
