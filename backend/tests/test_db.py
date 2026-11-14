"""Phase 1 database-foundation tests.

Covers:
- Engine/config wiring (SQLite dev default; URL from settings).
- Session factory behavior.
- The connectivity probe creates NO tables (schema stays empty in Phase 1).
- The health check's safe error contract: on failure the response/reason contains no
  exception text, driver names, hostnames, usernames, or connection strings.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.core.db import SessionLocal, build_engine, engine, probe_database


@pytest.mark.skipif(
    os.environ.get("DATABASE_URL", "sqlite:///./dev.db").startswith("postgresql"),
    reason="SQLite-default assertion applies only to the SQLite job",
)
def test_default_database_url_is_sqlite() -> None:
    settings = get_settings()
    assert settings.database_url.startswith("sqlite")


def test_engine_builds_and_connects() -> None:
    probe_engine = build_engine()
    ok, reason = probe_database(probe_engine)
    assert ok is True
    assert reason == ""
    probe_engine.dispose()


def test_probe_error_is_generic_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing probe must return only the generic 'error' token — never technical detail."""

    class ExplodingEngine:
        def connect(self) -> None:
            raise RuntimeError(
                "postgresql+pg8000://secret_user:super-secret-password@db-host-internal:5432/saas — boom"
            )

    ok, reason = probe_database(ExplodingEngine())  # type: ignore[arg-type]
    assert ok is False
    assert reason == "error"
    assert "secret_user" not in reason
    assert "super-secret-password" not in reason
    assert "db-host-internal" not in reason
    assert "boom" not in reason
    assert "pg8000" not in reason


def test_session_yields_and_closes() -> None:
    session = SessionLocal()
    try:
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        session.close()


def test_phase1_creates_no_tables() -> None:
    """Hard constraint: Phase 1 must not create database tables."""
    inspector = inspect(engine)
    assert inspector.get_table_names() == []
