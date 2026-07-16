"""add tables for the 16 Phase-9 platform modules (Blueprint 03..26)

36 additive tables defined in models_ext.py. Created from the model metadata
(checkfirst) so the migration and the models can never drift apart. No
existing table or column is touched.

Revision ID: d4e8b1c5a7f9
Revises: c7d1f0a2b9e4
Create Date: 2026-07-16 16:30:00.000000
"""
import os
import sys

from alembic import op

revision = 'd4e8b1c5a7f9'
down_revision = 'c7d1f0a2b9e4'
branch_labels = None
depends_on = None

# make drip_platform root importable when alembic runs from anywhere
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _tables():
    import models      # noqa: F401  (registers core tables on Base.metadata)
    import models_ext
    return [t.__table__ for t in models_ext.ALL_TABLES]


def upgrade():
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
