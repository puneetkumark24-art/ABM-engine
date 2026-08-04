"""
tests/conftest.py — collection-time guardrails.

Two files test the LEGACY Flask dashboard (dashboard/app.py), not the real
FastAPI SPA (routers/os_shell.py) that the platform now runs from — the
Flask app was deprecated this session (see "Start Dashboard.bat" and
PHASE notes) after it turned out to be the reason the real pipeline UI
looked "not in the dashboard": the desktop shortcut was opening the wrong
app. These two files also run their checks as top-level module code with a
bare `sys.exit(1)` on failure, which is fine for `python tests/test_x.py`
but is actively dangerous under plain pytest collection: pytest imports
every test_*.py file during collection, so a failing run here doesn't
report as a clean test failure -- it raises SystemExit at import time and
crashes the ENTIRE pytest session with an INTERNALERROR, hiding every other
file's results. Verified by running `pytest --collect-only tests/` before
this fix: it collected 46 items then hard-crashed on test_signal_decay.py.

Excluding them from automatic collection keeps CI's `pytest tests/` fast,
safe, and focused on the code that's actually running in production. They
remain fully runnable by hand for anyone still maintaining the legacy
dashboard: `python tests/test_signal_decay.py` / `test_signal_intel.py`.
"""
collect_ignore = [
    "test_signal_decay.py",
    "test_signal_intel.py",
]

# ---------------------------------------------------------------------------
# Preserve the CI/shell-configured DATABASE_URL before any test module gets a
# chance to overwrite it. pytest always imports conftest.py before collecting
# any test_*.py file in this directory, so this runs first, full stop.
#
# Several script-style suites (test_signal_v2_bridge.py, others) reassign
# os.environ["DATABASE_URL"] at module level to point at their own isolated
# temp-file SQLite DB, and never restore it. In a combined `pytest tests/`
# process that's harmless for THEM, but any later file that re-reads
# os.environ.get("DATABASE_URL") to decide "are we on Postgres" gets lied to.
# Caught for real: test_tenancy_rls.py's entire RLS-isolation proof -- the
# one check that actually matters in that file -- was silently reporting
# "skipped (needs PostgreSQL)" and the test still went green, whenever it
# happened to run after test_signal_v2_bridge.py in file-collection order.
import os  # noqa: E402
os.environ.setdefault("_ORIGINAL_DATABASE_URL", os.environ.get("DATABASE_URL", ""))

# ---------------------------------------------------------------------------
# Make Base.metadata complete for EVERY suite in the process.
#
# Most script-style suites call Base.metadata.drop_all() + create_all() in
# their setup. Against SQLite that is harmless. Against a real, already-
# `alembic upgrade head`-ed PostgreSQL -- which is exactly what CI runs -- it
# fails outright, because drop_all only knows about the model modules that
# particular file happened to import. A partial list means it tries to drop
# `opportunities` while `quotes.opportunity_id` (declared in models_crm2) is
# still pointing at it, and PostgreSQL correctly refuses:
#
#     psycopg2.errors.DependentObjectsStillExist:
#       cannot drop table opportunities because other objects depend on it
#
# Reproduced against a disposable PostgreSQL on test_sales_engagement.py,
# test_tracking_decision.py, test_sprint1_platform.py and
# test_security_compliance.py. Files that already carry a full import list
# (test_engine_e2e.py) pass -- the difference is only which modules are in
# Base.metadata at drop time, never the test logic itself.
#
# Importing every model module here fixes all of them at once, because pytest
# imports conftest.py before any test module and SQLAlchemy's registry is
# process-global. This is deliberately imports-only: it adds tables to the
# metadata registry and changes no behaviour, so it cannot mask a real defect.
# (Running a suite directly as `python tests/test_x.py` bypasses conftest and
# still depends on that file's own imports -- unchanged, and not the CI path.)
import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import models  # noqa: E402,F401
import models_ai, models_audit, models_collectors, models_crm2  # noqa: E402,F401
import models_ext, models_final, models_intel, models_jobs  # noqa: E402,F401
import models_llm, models_p10, models_p11, models_p12  # noqa: E402,F401
import models_s3, models_s6, models_s8  # noqa: E402,F401
import models_segments, models_tenant  # noqa: E402,F401
