"""partition the REAL event firehose tables (Gap-2)

Converts metric_events, delivery_events, web_events to monthly RANGE partitions
in place (Postgres only). ORM inserts are unchanged; Postgres routes each row to
the right monthly partition, and analytics_fast (which queries these tables)
gets partition pruning for free.

Checks are done in Python + each DDL is a direct op.execute (no plpgsql string
wrapping) to avoid nested-quote issues with the RLS policy.

Revision ID: h5f7a9c1e3b4
Revises: g4d6e8f0a2b3
Create Date: 2026-07-17 03:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'h5f7a9c1e3b4'
down_revision = 'g4d6e8f0a2b3'
branch_labels = None
depends_on = None

TABLES = ["metric_events", "delivery_events", "web_events"]
POLICY = ("coalesce(current_setting('app.current_tenant', true), '') = '' "
          "OR tenant_id::text = current_setting('app.current_tenant', true)")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("""
        CREATE OR REPLACE FUNCTION create_event_partition(p_table text, p_month date)
        RETURNS void AS $$
        DECLARE
          start_ts date := date_trunc('month', p_month);
          end_ts   date := (date_trunc('month', p_month) + interval '1 month');
          part     text := p_table || '_' || to_char(start_ts, 'YYYY_MM');
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part) THEN
            EXECUTE format(
              'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
              part, p_table, start_ts, end_ts);
          END IF;
        END; $$ LANGUAGE plpgsql""")

    for t in TABLES:
        exists = bind.execute(sa.text("SELECT to_regclass(:t)"), {"t": t}).scalar()
        if not exists:
            continue
        is_part = bind.execute(sa.text(
            "SELECT count(*) FROM pg_partitioned_table pt JOIN pg_class c "
            "ON c.oid = pt.partrelid WHERE c.relname = :t"), {"t": t}).scalar()
        if is_part:
            continue

        op.execute(f'ALTER TABLE {t} RENAME TO {t}_old')
        op.execute(f'CREATE TABLE {t} (LIKE {t}_old INCLUDING DEFAULTS) PARTITION BY RANGE (occurred_at)')
        op.execute(f'ALTER TABLE {t} ADD PRIMARY KEY (id, occurred_at)')
        op.execute(f'CREATE TABLE {t}_default PARTITION OF {t} DEFAULT')
        op.execute(f"SELECT create_event_partition('{t}', (now() - interval '1 month')::date)")
        op.execute(f"SELECT create_event_partition('{t}', now()::date)")
        op.execute(f"SELECT create_event_partition('{t}', (now() + interval '1 month')::date)")
        op.execute(f'INSERT INTO {t} SELECT * FROM {t}_old')
        op.execute(f'DROP TABLE {t}_old CASCADE')
        op.execute(f'ALTER TABLE {t} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {t} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({POLICY})")
        op.execute(f'CREATE INDEX idx_{t}_ttt ON {t} (tenant_id, event_type, occurred_at)')
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') "
            f"THEN GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO app_rw; END IF; END $$;")


def downgrade():
    # one-way (de-partitioning would require a data copy back); no-op guard.
    pass
