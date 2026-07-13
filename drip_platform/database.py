"""
database.py — engine/session setup.

Uses generic SQLAlchemy types (String for IDs, JSON) rather than Postgres-only
types (UUID, JSONB) so the exact same models run against SQLite (for local
dev/testing without a Postgres server) and PostgreSQL (production) without
changes. On Postgres, String(36) UUIDs and JSON columns work natively.

Auto-loads .env from this same folder so DATABASE_URL never has to be set
by hand in the shell (which is also what caused the Windows cmd.exe error:
`VAR=value command` is bash syntax, not cmd syntax — dotenv sidesteps the
whole problem by reading the file directly instead of relying on the shell).
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

load_dotenv(Path(__file__).parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./drip_dev.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
