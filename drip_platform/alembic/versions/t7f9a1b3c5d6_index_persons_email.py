"""index persons.primary_email -- production-readiness fix for the 30,000+
contact scale target.

Problem found during the production-readiness audit: `persons.primary_email`
had no index at all. At the current small dev dataset this doesn't show up,
but at 30k rows, any lookup or dedup-by-email (contact search, CRM import
matching, "does this person already exist" checks) becomes a full table
scan.

What this does NOT do, and why: it does not add a UNIQUE constraint on
primary_email. Enforcing uniqueness blindly on a live database could fail
the migration outright if any duplicate emails already exist in production
data (two contacts sharing a shared/team inbox, a data-entry duplicate,
etc.) -- and this migration was authored without access to the real
production data to check for that first. Adding a hard uniqueness
constraint should be a deliberate follow-up: run a duplicate-email report
first, resolve any real duplicates as a data-quality pass, then add the
constraint. Doing it silently here risks breaking the live database on
upgrade with no warning.

What this DOES do, additive and safe either way:
  - idx_persons_primary_email: a plain btree index for fast lookups.
  - idx_persons_primary_email_lower (Postgres only): a functional index on
    lower(primary_email), since email lookups/dedup are case-insensitive in
    practice (Person@Bank.com and person@bank.com are the same mailbox) and
    a plain index can't serve a case-insensitive query efficiently.

Both are pure index additions -- no column, table, or data change. Rollback
drops both indexes only.

Revision ID: t7f9a1b3c5d6
Revises: s6e8f0a2c4d5
Create Date: 2026-08-02 00:00:00.000000
"""
from alembic import op

revision = 't7f9a1b3c5d6'
down_revision = 's6e8f0a2c4d5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.create_index("idx_persons_primary_email", "persons", ["primary_email"])
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_persons_primary_email_lower "
            "ON persons (lower(primary_email))"
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_persons_primary_email_lower")
    op.drop_index("idx_persons_primary_email", table_name="persons")
