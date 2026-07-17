"""add CRM configurability tables: custom properties, saved views, tasks (Phase 12)

Revision ID: c9e6a4b8d2f0
Revises: b8d5f3a2c6e9
Create Date: 2026-07-16 21:30:00.000000
"""
import os
import sys

from alembic import op

revision = 'c9e6a4b8d2f0'
down_revision = 'b8d5f3a2c6e9'
branch_labels = None
depends_on = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models, models_ext, models_p10, models_p11  # noqa: F401
    import models_p12
    return [t.__table__ for t in models_p12.PHASE12_TABLES]


def upgrade():
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
