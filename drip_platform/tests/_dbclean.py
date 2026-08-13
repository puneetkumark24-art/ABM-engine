"""Foreign-key-safe database cleanup shared by the script-style suites.

Lives here rather than in conftest.py because pytest imports conftest under a
special name -- `import conftest` fails inside a test module -- and these
suites are also runnable directly as `python tests/test_x.py`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def purge_all(db) -> int:
    """Empty every mapped table in foreign-key-safe order.

    Suites that clean up with `db.query(Person).delete()` worked on SQLite,
    which did not enforce the constraints, and fail on PostgreSQL the moment
    another suite has left a referencing row behind -- a draft, a touch, an
    activity log. Hand-listing the child tables is whack-a-mole: it was drafts,
    then touches, and the next table to gain a person_id would break it again.

    SQLAlchemy already knows the dependency graph. `sorted_tables` is in
    creation order (parents first), so deleting in reverse is exactly
    children-before-parents, and it stays correct as the schema grows.
    """
    from database import Base
    n = 0
    for table in reversed(Base.metadata.sorted_tables):
        try:
            n += db.execute(table.delete()).rowcount or 0
        except Exception:          # table not present in this schema slice
            db.rollback()
    db.commit()
    return n
