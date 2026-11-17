"""B1.6 Step 1: isolated PostgreSQL 16 fixture foundation for FastAPI HTTP integration tests.

Responsibilities (narrow scope):
- create a uniquely named disposable PostgreSQL database
- run Alembic migrations to head (0004) against that database
- provide a dedicated SQLAlchemy engine/session factory bound to that database
- provide a fresh FastAPI app with dependency_overrides[get_db] -> disposable sessions
- provide a TestClient
- deterministically reset application tables before each test (explicit allowlist)
- teardown: remove overrides, dispose connections, drop only the exact disposable DB

Safety:
- explicit opt-in required: NORTHSTAR_ALLOW_DISPOSABLE_PG_TEST_DB=1
- dedicated test URL required: B16_TEST_DATABASE_URL (ordinary DATABASE_URL never authorizes create/drop)
- PostgreSQL URL parsed via SQLAlchemy URL parser with validated host/port allowlist
- fixed test server allowlist: loopback-only hosts {localhost, 127.0.0.1, ::1} and port {5432}
- no global app.core.db engine/session mutation
- no permanent DATABASE_URL/settings leakage (Alembic migration step is scoped+restored)
- no outer transaction rollback for HTTP isolation; reset via TRUNCATE between tests
- synthetic data only; disposable DB only
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Explicit reviewed allowlist of application tables (Alembic head 0004, 19 tables).
# alembic_version is intentionally excluded from reset operations.
APPLICATION_TABLES_ALLOWLIST: tuple[str, ...] = (
    "cart_items",
    "carts",
    "categories",
    "customer_addresses",
    "customers",
    "inventory_adjustments",
    "order_items",
    "order_status_history",
    "orders",
    "product_images",
    "products",
    "staff_users",
    "store_memberships",
    "store_order_counters",
    "storefront_footer_links",
    "storefront_sections",
    "storefront_settings",
    "storefront_slides",
    "stores",
)

_DISPOSABLE_DB_NAME_RE = re.compile(r"^api_pg_[0-9a-f]{12}$")

# Fixed, explicit test-server allowlist (loopback-only).
ALLOWED_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
ALLOWED_PORTS: frozenset[int] = frozenset({5432})


class B16FixtureConfigError(RuntimeError):
    """Invalid or unsafe B1.6 disposable PostgreSQL test configuration (must fail loudly)."""


def _guard_disposable_db_name(dbname: str) -> None:
    if not _DISPOSABLE_DB_NAME_RE.fullmatch(dbname):
        raise AssertionError(f"Refusing to operate on non-disposable database name: {dbname!r}")





def _validated_test_url() -> URL:
    """Parse and safety-validate B16_TEST_DATABASE_URL. Raises B16FixtureConfigError on unsafe/invalid config."""
    raw = os.environ.get("B16_TEST_DATABASE_URL")
    if raw is None or not raw.strip():
        # Genuine absence handled by caller as skip when opt-in/config absent.
        raise B16FixtureConfigError("B16_TEST_DATABASE_URL is required")

    try:
        url = make_url(raw)
    except ArgumentError as exc:
        raise B16FixtureConfigError(f"Invalid B16_TEST_DATABASE_URL: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise B16FixtureConfigError(f"Invalid B16_TEST_DATABASE_URL: {type(exc).__name__}") from exc

    driver = (url.drivername or "").lower()
    if not (driver == "postgresql" or driver.startswith("postgresql+")):
        raise B16FixtureConfigError("B16_TEST_DATABASE_URL must be a PostgreSQL URL")

    host = (url.host or "").strip()
    if not host:
        raise B16FixtureConfigError("B16_TEST_DATABASE_URL must specify an explicit hostname")
    host_normalized = host.lower()

    port = url.port if url.port is not None else 5432

    if host_normalized not in ALLOWED_HOSTS:
        raise B16FixtureConfigError(
            f"B16_TEST_DATABASE_URL host {host_normalized!r} is not in the fixed test-server allowlist"
        )
    if port not in ALLOWED_PORTS:
        raise B16FixtureConfigError(
            f"B16_TEST_DATABASE_URL port {port} is not in the fixed test-server allowlist"
        )

    if not url.database:
        raise B16FixtureConfigError("B16_TEST_DATABASE_URL must include a database name/path segment")

    return url


def _is_explicit_opt_in_enabled() -> bool:
    return os.environ.get("NORTHSTAR_ALLOW_DISPOSABLE_PG_TEST_DB") == "1"


def _server_maintenance_url(validated: URL) -> str:
    # Connect to maintenance DB only after all safety checks pass; never include credentials in reports.
    maintenance = validated.set(database="postgres")
    return maintenance.render_as_string(hide_password=False)


def _generated_database_url(validated: URL, dbname: str) -> str:
    return validated.set(database=dbname).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def pg_api_database_url() -> Generator[str, None, None]:
    """Create, migrate, yield, and drop a dedicated disposable PostgreSQL database.

    Skips only when required test configuration is genuinely absent (no explicit opt-in or no
    dedicated B16_TEST_DATABASE_URL). Invalid/unsafe configuration or actual DB/migration failures
    fail loudly.
    """
    if not _is_explicit_opt_in_enabled():
        pytest.skip(
            "B1.6 disposable PostgreSQL fixture requires explicit opt-in "
            "NORTHSTAR_ALLOW_DISPOSABLE_PG_TEST_DB=1"
        )

    b16_url_raw = os.environ.get("B16_TEST_DATABASE_URL")
    if b16_url_raw is None or not b16_url_raw.strip():
        pytest.skip("B1.6 disposable PostgreSQL fixture requires B16_TEST_DATABASE_URL")

    # All safety checks (parse, PostgreSQL, host/port allowlist) must pass before any connection.
    validated = _validated_test_url()

    dbname = f"api_pg_{uuid.uuid4().hex[:12]}"
    _guard_disposable_db_name(dbname)

    admin_url = _server_maintenance_url(validated)
    db_url = _generated_database_url(validated, dbname)

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    created = False
    cleanup_errors: list[str] = []

    try:
        # Create only the generated disposable database (after safety checks).
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
        created = True

        # Alembic reads URL from app settings (DATABASE_URL env + lru_cache). Scope and restore.
        from alembic import command
        from alembic.config import Config
        from app.core.config import get_settings

        previous_env = os.environ.get("DATABASE_URL")
        migration_exc: BaseException | None = None
        try:
            os.environ["DATABASE_URL"] = db_url
            get_settings.cache_clear()
            cfg = Config(str(BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
            command.upgrade(cfg, "head")
        except BaseException as exc:  # noqa: BLE001
            migration_exc = exc
        finally:
            try:
                if previous_env is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = previous_env
                get_settings.cache_clear()
            except BaseException as restore_exc:  # noqa: BLE001
                if migration_exc is None:
                    raise
                print(
                    f"Failed to restore DATABASE_URL/settings cache after Alembic migration for {dbname!r}: "
                    f"{restore_exc!r}",
                    file=sys.stderr,
                )
        if migration_exc is not None:
            raise migration_exc

        yield db_url
    finally:
        if created:
            _guard_disposable_db_name(dbname)
            try:
                with admin.connect() as conn:
                    conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(f"drop disposable database {dbname!r}: {exc!r}")
        try:
            admin.dispose()
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"dispose admin engine for {dbname!r}: {exc!r}")
        if cleanup_errors:
            for err in cleanup_errors:
                print(f"CLEANUP ERROR: {err}", file=sys.stderr)
            raise RuntimeError("Disposable PostgreSQL fixture cleanup failed: " + "; ".join(cleanup_errors))


@pytest.fixture(scope="session")
def pg_api_engine(pg_api_database_url: str) -> Generator[Engine, None, None]:
    engine = create_engine(pg_api_database_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pg_api_session_factory(pg_api_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_api_engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture(scope="session")
def pg_api_app(pg_api_session_factory: sessionmaker[Session]):
    """Fresh FastAPI app wired to the disposable PostgreSQL DB via dependency override only."""
    from app.core.db import get_db
    from app.main import create_app

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        db = pg_api_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def pg_api_client(pg_api_app) -> Generator[TestClient, None, None]:
    with TestClient(pg_api_app) as client:
        yield client


def _reset_application_tables(engine: Engine) -> None:
    # Explicit reviewed allowlist only; alembic_version excluded by construction.
    quoted = ", ".join(f'"{name}"' for name in APPLICATION_TABLES_ALLOWLIST)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _clean_pg_api_database(pg_api_engine: Engine) -> Generator[None, None, None]:
    """Ensure each test starts with a clean application-data state."""
    _reset_application_tables(pg_api_engine)
    yield
    # No post-test rollback: API requests may commit via overridden sessions.
    # Next test's pre-reset guarantees isolation. Best-effort post reset not required.
