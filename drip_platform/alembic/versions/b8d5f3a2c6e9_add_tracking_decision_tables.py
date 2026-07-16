"""add tracking stack + deliverability + AI Decision Engine tables (Phase 11)

Six additive tables from models_p11.py.

Revision ID: b8d5f3a2c6e9
Revises: a7c4e2f1d8b3
Create Date: 2026-07-16 20:00:00.000000
"""
import os
import sys

from alembic import op

revision = 'b8d5f3a2c6e9'
down_revision = 'a7c4e2f1d8b3'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models      # noqa: F401
    import models_ext  # noqa: F401
    import models_p10  # noqa: F401
    import models_p11
    return [t.__table__ for t in models_p11.PHASE11_TABLES]


def upgrade():
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
