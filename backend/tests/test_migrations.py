"""Phase 2 migration tests (PostgreSQL-only; disposable database via conftest).

Verifies the four hand-written migrations end-to-end on PostgreSQL: exact
table set after upgrade, revision head, and a full downgrade/re-upgrade
cycle. These tests CANNOT run on SQLite (the DDL is PostgreSQL-authored).
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

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


@requires_pg
def test_upgrade_creates_exactly_19_tables(pg_database_url):
    engine = create_engine(pg_database_url)
    try:
        tables = inspect(engine).get_table_names()
        assert sorted(tables) == EXPECTED_TABLES, tables
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
    """Self-restoring cycle: downgrade to base -> zero tables -> upgrade head."""
    import os

    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings

    original_url = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = pg_database_url
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.downgrade(cfg, "base")
        engine = create_engine(pg_database_url)
        try:
            remaining = [t for t in inspect(engine).get_table_names()]
            assert remaining == [], remaining
        finally:
            engine.dispose()
        command.upgrade(cfg, "head")
        engine = create_engine(pg_database_url)
        try:
            assert sorted(inspect(engine).get_table_names()) == EXPECTED_TABLES
        finally:
            engine.dispose()
    finally:
        os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()


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
