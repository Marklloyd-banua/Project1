"""Phase 2 test fixtures and helpers.

PostgreSQL tests run ONLY against an isolated, disposable database:
`phase2_ci_<random>` created from the CI DATABASE_URL's server, migrated with
`alembic upgrade head`, and dropped afterwards. The main DATABASE_URL database
is never touched by Phase 2 tests (Phase 1's "no tables" contract holds).

Nothing here runs locally on Termux (pytest/pydantic unavailable) — GitHub
Actions is the authoritative verification.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parent.parent


def is_postgres() -> bool:
    return os.environ.get("DATABASE_URL", "sqlite:///./dev.db").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not is_postgres(), reason="PostgreSQL-only verification (Phase 2)"
)


def _split_url(url: str) -> tuple[str, str]:
    """Return (server_url, database_name) from a SQLAlchemy database URL."""
    # postgresql+pg8000://user:pass@host:port/dbname  ->  server url + dbname
    prefix, dbname = url.rsplit("/", 1)
    return prefix, dbname


def _with_credentials(url: str, user: str, password: str) -> str:
    """Replace the userinfo segment of a database URL."""
    parts = urlsplit(url)
    host = parts.netloc.split("@", 1)[-1]
    return urlunsplit((parts.scheme, f"{user}:{password}@{host}", parts.path, "", ""))


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    """Create, migrate, yield, and drop a disposable PostgreSQL database."""
    if not is_postgres():
        pytest.skip("PostgreSQL-only fixture")
    original_url = os.environ["DATABASE_URL"]
    server_url, _ = _split_url(original_url)
    dbname = f"phase2_ci_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server_url + "/postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    except Exception:
        admin.dispose()
        pytest.skip(f"could not create disposable test database ({dbname})")

    url = f"{server_url}/{dbname}"
    # alembic/env.py injects the URL from app.core.config (DATABASE_URL env +
    # lru_cache), so point the environment at the disposable database for the
    # duration of the migration run, then restore.
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings

    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
    finally:
        os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()
    yield url

    # Teardown: downgrade is implicit — the database itself is dropped.
    admin2 = create_engine(server_url + "/postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin2.connect() as conn:
            # WITH (FORCE): PG 13+ closes any lingering connections first.
            conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
    finally:
        admin2.dispose()


@pytest.fixture(scope="session")
def pg_engine(pg_database_url):
    engine = create_engine(pg_database_url, future=True)
    yield engine
    engine.dispose()


def expect_error(engine, sql: str, params: dict | None = None, match: str | None = None):
    """Execute a statement on its own connection, expecting a database error.

    Returns the exception so tests can assert SQLSTATE/message specifics.
    Rolls back so the error does not poison other connections.
    """
    with engine.connect() as conn:
        try:
            conn.execute(text(sql), params or {})
            conn.rollback()
        except Exception as exc:  # noqa: BLE001 — deliberate: any DB error is expected here
            conn.rollback()
            if match and match not in str(exc):
                raise AssertionError(f"error {exc!r} does not contain {match!r}") from exc
            return exc
    raise AssertionError(f"expected error for: {sql}")


def exec_sql(engine, sql: str, params: dict | None = None):
    """Execute a statement in its own committed transaction."""
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})


def seed_stores_and_catalog(engine) -> dict:
    """Seed staff, two stores (counters auto-created by the 0001 trigger),
    one category and one product in store A. Returns a dict of identifiers."""
    ids: dict = {}
    suffix = uuid.uuid4().hex[:8]
    ids["staff_id"] = exec_sql(
        engine,
        "INSERT INTO staff_users (email, full_name) "
        "VALUES (:email, :name) RETURNING id",
        {"email": f"admin-{suffix}@example.com", "name": "Admin"},
    ).scalar_one()
    ids["store_a"] = exec_sql(
        engine,
        "INSERT INTO stores (name, owner, domain) VALUES (:n, :o, :d) RETURNING id",
        {"n": "Store A", "o": "Owner A", "d": f"storea-{suffix}.example.com"},
    ).scalar_one()
    ids["store_b"] = exec_sql(
        engine,
        "INSERT INTO stores (name, owner, domain) VALUES (:n, :o, :d) RETURNING id",
        {"n": "Store B", "o": "Owner B", "d": f"storeb-{suffix}.example.com"},
    ).scalar_one()
    ids["category_a"] = exec_sql(
        engine,
        "INSERT INTO categories (store_id, name, slug) "
        "VALUES (:s, 'Clothing', 'clothing') RETURNING id",
        {"s": ids["store_a"]},
    ).scalar_one()
    ids["product_a"] = exec_sql(
        engine,
        "INSERT INTO products (store_id, name, slug, price, stock_quantity, "
        "category, category_id) VALUES (:s, 'Tee', 'tee', 10.00, 5, 'Clothing', "
        ":c) RETURNING id",
        {"s": ids["store_a"], "c": ids["category_a"]},
    ).scalar_one()
    return ids
