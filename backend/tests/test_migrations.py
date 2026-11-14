"""Phase 2 migration tests (PostgreSQL-only; disposable database via conftest).

Verifies the four hand-written migrations end-to-end on PostgreSQL: exact
application-table set after upgrade, revision head, and a full
downgrade/re-upgrade cycle. These tests CANNOT run on SQLite (the DDL is
PostgreSQL-authored).
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from tests.conftest import exec_sql, pg_database_url  # noqa: F401 (fixtures)
from tests.conftest import BACKEND_DIR, requires_pg

EXPECTED_TABLES = sorted(
    [
        "staff_users", "stores", "store_memberships", "store_order_counters",
        "categories", "products", "product_images", "inventory_adjustments",
        "storefront_slides", "storefront_sections", "storefront_settings",
        "storefront_footer_links", "customers", "customer_addresses", "carts",
        "cart_items", "orders", "order_items", "order_status_history",
    ]
)


def _application_tables(engine):
    """Application tables only; Alembic's bookkeeping table is excluded."""
    return sorted(t for t in inspect(engine).get_table_names() if t != "alembic_version")


@requires_pg
def test_upgrade_creates_exactly_19_tables(pg_database_url):
    engine = create_engine(pg_database_url)
    try:
        assert _application_tables(engine) == EXPECTED_TABLES
    finally:
        engine.dispose()


@requires_pg
def test_alembic_version_head_is_0004(pg_database_url):
    engine = create_engine(pg_database_url)
    try:
        version = exec_sql(engine, "SELECT version_num FROM alembic_version").scalar_one()
        assert version == "0004"
    finally:
        engine.dispose()


@requires_pg
def test_full_downgrade_base_then_reupgrade(pg_database_url):
    """Isolated cycle: downgrade to base -> no app tables -> upgrade head.

    Runs against a dedicated disposable database so the session-shared
    pg_database_url fixture is never mutated/corrupted by this test.
    """
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings

    parsed = make_url(pg_database_url)
    dbname = f"phase2_downgrade_{uuid.uuid4().hex[:12]}"
    admin_url = parsed.set(database="postgres")
    url = parsed.set(database=dbname)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        admin.dispose()
    original_url = os.environ.get("DATABASE_URL")
    primary_exc: Exception | None = None
    try:
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        engine = create_engine(url)
        try:
            assert _application_tables(engine) == [], _application_tables(engine)
        finally:
            engine.dispose()
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            assert _application_tables(engine) == EXPECTED_TABLES
        finally:
            engine.dispose()
    except Exception as exc:
        primary_exc = exc
        raise
    finally:
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()
        admin2 = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with admin2.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        except Exception as cleanup_exc:
            if primary_exc is not None:
                raise cleanup_exc from primary_exc
            raise
        finally:
            admin2.dispose()


@requires_pg
def test_counter_trigger_initialized_for_every_store(pg_database_url):
    engine = create_engine(pg_database_url)
    try:
        store_id = exec_sql(
            engine,
            "INSERT INTO stores (name, owner, domain) VALUES ('T', 'O', :d) RETURNING id",
            {"d": "counter-test.example.com"},
        ).scalar_one()
        row = exec_sql(
            engine,
            "SELECT last_order_number FROM store_order_counters WHERE store_id = :s",
            {"s": store_id},
        ).scalar_one()
        assert row == 0, "trigger must initialize the counter at 0"
    finally:
        engine.dispose()
