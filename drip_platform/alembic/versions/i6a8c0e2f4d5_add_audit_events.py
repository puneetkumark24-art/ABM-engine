"""add append-only audit_events table (Sprint 1, S1-03)

Revision ID: i6a8c0e2f4d5
Revises: h5f7a9c1e3b4
Create Date: 2026-07-17 04:00:00.000000
"""
import os
import sys
from alembic import op

revision = 'i6a8c0e2f4d5'
down_revision = 'h5f7a9c1e3b4'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models_audit
    return [t.__table__ for t in models_audit.AUDIT_TABLES]


def upgrade():
    bind = op.get_bind()
    for t in _tables():
        t.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for t in reversed(_tables()):
        t.drop(bind=bind, checkfirst=True)
