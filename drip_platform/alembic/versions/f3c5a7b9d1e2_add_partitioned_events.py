"""add monthly range-partitioned event table pattern (P0-D)

Demonstrates + provides the production pattern for the 100M-row firehose without
touching the existing metric_events (a plain table can't be ALTERed into a
partitioned one). `metric_events_part` is RANGE-partitioned by occurred_at with
monthly children + a default catch-all, native uuid PK (UUIDv7-friendly), and a
composite index. A `create_month_partition()` helper (also callable by a
scheduled worker) provisions future months.

Postgres-only. On SQLite this is a no-op (partitioning is a PG feature).

Revision ID: f3c5a7b9d1e2
Revises: e2b4c6d8f0a1
Create Date: 2026-07-17 01:00:00.000000
"""
from alembic import op

revision = 'f3c5a7b9d1e2'
down_revision = 'e2b4c6d8f0a1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("""
        CREATE TABLE IF NOT EXISTS metric_events_part (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            tenant_id uuid,
            event_type text NOT NULL,
            subject_type text,
            subject_id uuid,
            props jsonb DEFAULT '{}'::jsonb,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)""")

    # composite index the analytics queries use (per partition automatically)
    op.execute("""CREATE INDEX IF NOT EXISTS idx_mep_type_time
                  ON metric_events_part (tenant_id, event_type, occurred_at)""")

    # default catch-all so inserts never fail even before a month partition exists
    op.execute("""CREATE TABLE IF NOT EXISTS metric_events_part_default
                  PARTITION OF metric_events_part DEFAULT""")

    # a helper function to provision a month's partition (idempotent);
    # a scheduled worker calls this monthly.
    op.execute("""
        CREATE OR REPLACE FUNCTION create_month_partition(p_month date)
        RETURNS void AS $$
        DECLARE
          start_ts date := date_trunc('month', p_month);
          end_ts   date := (date_trunc('month', p_month) + interval '1 month');
          part     text := 'metric_events_part_' || to_char(start_ts, 'YYYY_MM');
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part) THEN
            EXECUTE format(
              'CREATE TABLE %I PARTITION OF metric_events_part FOR VALUES FROM (%L) TO (%L)',
              part, start_ts, end_ts);
          END IF;
        END; $$ LANGUAGE plpgsql""")

    # provision current, previous, and next month up front
    op.execute("SELECT create_month_partition(now()::date)")
    op.execute("SELECT create_month_partition((now() - interval '1 month')::date)")
    op.execute("SELECT create_month_partition((now() + interval '1 month')::date)")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP FUNCTION IF EXISTS create_month_partition(date)")
    op.execute("DROP TABLE IF EXISTS metric_events_part CASCADE")
