"""Minimal B1.6 Step 1 smoke tests for the PostgreSQL API integration fixture.

Validates (against PostgreSQL 16 + Alembic-migrated disposable DB):
- TestClient is wired to the migrated disposable PostgreSQL database via dependency_overrides[get_db]
- Alembic schema is at head 0004 and expected application tables exist
- a request/session obtained through the overridden get_db dependency uses the disposable DB
- each test starts from a clean application-data state (deterministic reset)

Scope: fixture foundation only. No endpoint/authorization/resource behavior tests.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import EXPECTED_TABLE_NAMES


def _db_name_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def test_smoke_connected_migrated_and_overridden_get_db(
    pg_api_client,
    pg_api_app,
    pg_api_engine,
    pg_api_database_url,
):
    expected_db = _db_name_from_url(pg_api_database_url)

    # Alembic head is 0004 (authoritative migration chain).
    with pg_api_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0004"

    # Expected application tables exist (19 tables, excluding alembic_version).
    with pg_api_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        ).scalars().all()
    table_names = set(rows)
    assert "alembic_version" in table_names
    assert set(EXPECTED_TABLE_NAMES) == (table_names - {"alembic_version"})
    assert len(EXPECTED_TABLE_NAMES) == 19

    # HTTP/TestClient path uses the overridden get_db dependency against disposable DB.
    path = "/__b16_pg_smoke_dbname"
    added = False

    async def _db_name_probe(db: Session = Depends(get_db)):
        return {"db": db.execute(text("SELECT current_database()")).scalar_one()}

    if not any(getattr(r, "path", None) == path for r in pg_api_app.router.routes):
        pg_api_app.add_api_route(path, _db_name_probe, methods=["GET"])
        added = True
    try:
        response = pg_api_client.get(path)
        assert response.status_code == 200
        assert response.json()["db"] == expected_db
    finally:
        if added:
            pg_api_app.router.routes = [
                r for r in pg_api_app.router.routes if getattr(r, "path", None) != path
            ]

    # Direct invocation of the overridden dependency yields a session on the disposable DB.
    override = pg_api_app.dependency_overrides[get_db]
    gen = override()
    db = next(gen)
    try:
        assert db.execute(text("SELECT current_database()")).scalar_one() == expected_db
    finally:
        gen.close()


def test_smoke_clean_state_first_insert(pg_api_session_factory):
    # Starts clean (autouse reset). Insert synthetic data to prove reset on next test.
    suffix = uuid4().hex[:8]
    with pg_api_session_factory.begin() as db:
        count = db.execute(text("SELECT COUNT(*) FROM staff_users")).scalar_one()
        assert count == 0
        db.execute(
            text(
                "INSERT INTO staff_users (email, full_name) VALUES (:email, :name)"
            ),
            {"email": f"smoke-{suffix}@example.test", "name": "Smoke User"},
        )
        count_after = db.execute(text("SELECT COUNT(*) FROM staff_users")).scalar_one()
    assert count_after == 1


def test_smoke_clean_state_second_starts_empty(pg_api_session_factory):
    # Proves deterministic per-test reset: previous test's insert must not persist.
    with pg_api_session_factory.begin() as db:
        count = db.execute(text("SELECT COUNT(*) FROM staff_users")).scalar_one()
    assert count == 0
