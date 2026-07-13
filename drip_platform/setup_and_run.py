"""
setup_and_run.py — ONE COMMAND to stand up DRIP on your real PostgreSQL.

    python setup_and_run.py

What it does, in order, all automatically:
  1. Loads DATABASE_URL + DECIMAL_ABM_SQLITE_PATH from .env
  2. Connects to your Postgres SERVER (not the app db) and creates the
     `drip` database if it doesn't already exist
  3. Runs `alembic upgrade head` to create all tables
  4. Runs the ETL migration from your live decimal_abm SQLite database
  5. Prints the command to start the API (does not auto-launch it, so this
     script can finish and hand control back to you)

Safe to re-run: every step is idempotent (CREATE DATABASE IF NOT EXISTS,
Alembic no-ops if already at head, ETL skips rows that already exist).

Requires: PostgreSQL already installed and running on this machine
(this script cannot install or start Postgres itself — only Windows/macOS
admin tools or your package manager can do that).
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote

HERE = Path(__file__).parent


def load_env():
    env_path = HERE / ".env"
    if not env_path.exists():
        print(f"ERROR: {env_path} not found. Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def step(n, total, msg):
    print(f"\n[{n}/{total}] {msg}")


def ensure_database_exists(database_url: str):
    """Connects to the Postgres server's default 'postgres' db and creates
    the target database if missing — this is the one thing Alembic can't do
    for you (it can only create tables inside a database that already exists)."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    parsed = urlparse(database_url.replace("postgresql+psycopg2", "postgresql"))
    target_db = parsed.path.lstrip("/")
    admin_dsn = dict(
        host=parsed.hostname, port=parsed.port or 5432,
        user=parsed.username, password=unquote(parsed.password or ""),
        dbname="postgres",
    )
    try:
        conn = psycopg2.connect(**admin_dsn)
    except Exception as e:
        print(f"\nCould NOT reach PostgreSQL at {parsed.hostname}:{parsed.port}.")
        print("Checklist:")
        print("  - Is PostgreSQL actually installed and running on this machine?")
        print("  - Windows: check Services -> postgresql-x64-<version> is 'Running'")
        print("  - Does the user/password in .env match what you set when installing Postgres?")
        print(f"\nRaw error: {e}")
        sys.exit(1)

    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
    if cur.fetchone():
        print(f"  Database '{target_db}' already exists — skipping creation.")
    else:
        cur.execute(f'CREATE DATABASE "{target_db}"')
        print(f"  Created database '{target_db}'.")
    cur.close()
    conn.close()


def run(cmd: list[str]):
    print("  $", " ".join(cmd))
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"\nCommand failed with exit code {result.returncode}: {' '.join(cmd)}")
        sys.exit(result.returncode)


def main():
    load_env()
    database_url = os.environ["DATABASE_URL"]
    sqlite_path = os.environ.get("DECIMAL_ABM_SQLITE_PATH")

    total = 4
    step(1, total, "Ensuring 'drip' database exists on your Postgres server...")
    ensure_database_exists(database_url)

    step(2, total, "Running Alembic migrations (creates all tables)...")
    os.environ["DATABASE_URL"] = database_url  # visible to alembic/env.py
    run([sys.executable, "-m", "alembic", "upgrade", "head"])

    if sqlite_path and Path(sqlite_path).exists():
        step(3, total, f"Migrating data from {sqlite_path}...")
        run([sys.executable, "etl/migrate_from_decimal_abm.py", "--sqlite-path", sqlite_path])
    else:
        step(3, total, "SKIPPED — DECIMAL_ABM_SQLITE_PATH not set or file not found.")
        print(f"  (looked for: {sqlite_path})")
        print("  Set DECIMAL_ABM_SQLITE_PATH in .env and re-run this script to load your data.")

    step(4, total, "Done. Start the API with:")
    print(f"\n    DATABASE_URL=\"{database_url}\" python -m uvicorn main:app --reload\n")
    print("Then open http://127.0.0.1:8000/docs to explore it interactively.")


if __name__ == "__main__":
    main()
