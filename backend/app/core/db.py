"""Database engine and session management (SQLAlchemy 2.x).

Phase 1 foundation only:
- Engine/session are built from `DATABASE_URL` (SQLite dev default; PostgreSQL via any
  SQLAlchemy-supported driver segment, e.g. `postgresql+pg8000://` on Termux).
- No models, no tables, no migrations in this phase. The health check uses a
  driver-level `SELECT 1` connectivity probe that creates no schema.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine() -> Engine:
    """Create the engine from configuration. Called once per process."""
    url = get_settings().database_url
    # SQLite needs a thread-local connection for FastAPI's threadpool; PG drivers do not.
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    return create_engine(url, future=True)


def probe_database(engine: Engine) -> tuple[bool, str]:
    """Connectivity probe that creates no tables.

    Returns (ok, constant_reason). `constant_reason` is a fixed generic token — it must
    NEVER contain exception text, driver names, hostnames, usernames, or the URL.
    Technical details are logged server-side by the caller.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, ""
    except Exception:  # noqa: BLE001 — deliberately broad: any failure is a generic "error".
        # Server-side only: full exception/traceback goes to the application log.
        import logging

        logging.getLogger(__name__).exception("Database connectivity probe failed.")
        return False, "error"


engine: Engine = build_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
