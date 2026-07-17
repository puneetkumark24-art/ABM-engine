"""add durable job queue + transactional outbox (P0-B)

Two additive system tables. Not tenant-RLS'd — the worker tier is a trusted
system component that operates across tenants and sets tenant context per job
when executing handlers.

Revision ID: e2b4c6d8f0a1
Revises: d1a2b3c4e5f6
Create Date: 2026-07-17 00:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'e2b4c6d8f0a1'
down_revision = 'd1a2b3c4e5f6'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models_jobs
    return [t.__table__ for t in models_jobs.JOBS_TABLES]


def upgrade():
    bind = op.get_bind()
    for t in _tables():
        t.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for t in reversed(_tables()):
        t.drop(bind=bind, checkfirst=True)
