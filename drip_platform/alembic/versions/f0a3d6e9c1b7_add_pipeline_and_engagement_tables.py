"""add Pipeline Engine + PersonEngagement tables (Phase 10)

Four additive tables from models_p10.py — no existing table or column altered.

Revision ID: f0a3d6e9c1b7
Revises: d4e8b1c5a7f9
Create Date: 2026-07-16 18:00:00.000000
"""
import os
import sys

from alembic import op

revision = 'f0a3d6e9c1b7'
down_revision = 'd4e8b1c5a7f9'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models      # noqa: F401
    import models_ext  # noqa: F401  (FKs may reference extension tables)
    import models_p10
    return [t.__table__ for t in models_p10.PHASE10_TABLES]


def upgrade():
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
