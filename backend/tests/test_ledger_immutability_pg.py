"""Phase 2 append-only ledger tests (PostgreSQL-only; disposable database).

Creates a disposable least-privilege runtime role (SELECT/INSERT on the two
ledgers only) and asserts, against PostgreSQL:
  - INSERT succeeds (ledger rows are creatable at runtime),
  - UPDATE and DELETE are rejected with SQLSTATE 42501
    (insufficient_privilege) on BOTH ledgers,
  - the owner/migration role can still UPDATE (schema-surgery path intact).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import (
    exec_sql,
    pg_database_url,  # noqa: F401 (fixture)
    pg_engine,  # noqa: F401 (fixture)
    requires_pg,
    seed_stores_and_catalog,
    _split_url,
    _with_credentials,
)

LEDGERS = ("inventory_adjustments", "order_status_history")
RUNTIME_ROLE = "ci_runtime_phase2"
RUNTIME_PASSWORD = "ci_runtime_phase2_pw"


@pytest.fixture(scope="module")
def runtime_role(pg_engine, pg_database_url):
    server_url, _ = _split_url(pg_database_url)
    runtime_url = _with_credentials(pg_database_url, RUNTIME_ROLE, RUNTIME_PASSWORD)
    # Fresh role for this module (idempotent against leftovers).
    exec_sql(pg_engine, f"DROP ROLE IF EXISTS {RUNTIME_ROLE}")
    exec_sql(pg_engine, f"CREATE ROLE {RUNTIME_ROLE} LOGIN PASSWORD '{RUNTIME_PASSWORD}'")
    exec_sql(pg_engine, f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE}")
    for ledger in LEDGERS:
        exec_sql(
            pg_engine,
            f"GRANT SELECT, INSERT ON {ledger} TO {RUNTIME_ROLE}",
        )
        exec_sql(
            pg_engine,
            f"REVOKE UPDATE, DELETE ON {ledger} FROM {RUNTIME_ROLE}",
        )
    try:
        yield runtime_url
    finally:
        # Cleanup: revoke dependent privileges before dropping the role so
        # DROP ROLE succeeds even when a test raised an exception.
        for ledger in LEDGERS:
            exec_sql(
                pg_engine,
                f"REVOKE ALL PRIVILEGES ON {ledger} FROM {RUNTIME_ROLE}",
            )
        exec_sql(
            pg_engine,
            f"REVOKE USAGE ON SCHEMA public FROM {RUNTIME_ROLE}",
        )
        exec_sql(pg_engine, f"DROP ROLE IF EXISTS {RUNTIME_ROLE}")


@pytest.fixture()
def runtime_engine(runtime_role):
    from sqlalchemy import create_engine

    engine = create_engine(runtime_role, future=True)
    yield engine
    engine.dispose()


def _assert_42501(exc: Exception) -> None:
    orig = getattr(exc, "orig", None)
    sqlstate = (
        getattr(orig, "sqlstate", None)
        or getattr(orig, "pgcode", None)
        or ""
    )
    assert str(sqlstate) == "42501" or "42501" in str(exc) or "insufficient_privilege" in str(exc).lower(), (
        f"expected 42501 insufficient_privilege, got: {exc!r}"
    )


def _seed_ledger_row(pg_engine, ids, ledger: str):
    if ledger == "inventory_adjustments":
        exec_sql(
            pg_engine,
            "INSERT INTO inventory_adjustments (store_id, product_id, "
            "adjustment_amount, previous_quantity, new_quantity, reason) "
            "VALUES (:s, :p, 1, 4, 5, 'seed')",
            {"s": ids["store_a"], "p": ids["product_a"]},
        )
        return exec_sql(
            pg_engine,
            "SELECT id FROM inventory_adjustments WHERE store_id = :s "
            "ORDER BY created_at DESC LIMIT 1",
            {"s": ids["store_a"]},
        ).scalar_one()
    order = exec_sql(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, :n, 'C', 'c@example.com', 0, 0, 0, 0, 'USD', "
        "'L', 'C', '123', 'US') RETURNING id",
        {"s": ids["store_a"], "n": f"ORD-{uuid.uuid4().hex[:6].upper()}"},
    ).scalar_one()
    exec_sql(
        pg_engine,
        "INSERT INTO order_status_history (store_id, order_id, "
        "previous_status, new_status, reason) "
        "VALUES (:s, :o, 'Unpaid', 'Pending', 'seed')",
        {"s": ids["store_a"], "o": order},
    )
    return exec_sql(
        pg_engine,
        "SELECT id FROM order_status_history WHERE store_id = :s "
        "ORDER BY created_at DESC LIMIT 1",
        {"s": ids["store_a"]},
    ).scalar_one()


@requires_pg
def test_runtime_insert_succeeds_on_both_ledgers(pg_engine, runtime_engine):
    ids = seed_stores_and_catalog(pg_engine)
    # inventory_adjustments: runtime INSERT must work (new_quantity math valid).
    product = exec_sql(
        pg_engine,
        "SELECT id FROM products WHERE store_id = :s LIMIT 1",
        {"s": ids["store_a"]},
    ).scalar_one()
    with runtime_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO inventory_adjustments (store_id, product_id, "
                "adjustment_amount, previous_quantity, new_quantity, reason) "
                "VALUES (:s, :p, 1, 0, 1, 'runtime insert')"
            ),
            {"s": ids["store_a"], "p": product},
        )
    # order_status_history: runtime INSERT must work.
    order = exec_sql(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, :n, 'C', 'c@example.com', 0, 0, 0, 0, 'USD', "
        "'L', 'C', '123', 'US') RETURNING id",
        {"s": ids["store_a"], "n": f"ORD-{uuid.uuid4().hex[:6].upper()}"},
    ).scalar_one()
    with runtime_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO order_status_history (store_id, order_id, "
                "previous_status, new_status, reason) "
                "VALUES (:s, :o, 'Unpaid', 'Pending', 'runtime insert')"
            ),
            {"s": ids["store_a"], "o": order},
        )


@requires_pg
@pytest.mark.parametrize("ledger", LEDGERS)
def test_runtime_update_rejected_42501(pg_engine, runtime_engine, ledger):
    ids = seed_stores_and_catalog(pg_engine)
    row_id = _seed_ledger_row(pg_engine, ids, ledger)
    with pytest.raises(DBAPIError) as excinfo:
        with runtime_engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {ledger} SET reason = 'tampered' WHERE id = :i"),
                {"i": row_id},
            )
    _assert_42501(excinfo.value)


@requires_pg
@pytest.mark.parametrize("ledger", LEDGERS)
def test_runtime_delete_rejected_42501(pg_engine, runtime_engine, ledger):
    ids = seed_stores_and_catalog(pg_engine)
    row_id = _seed_ledger_row(pg_engine, ids, ledger)
    with pytest.raises(DBAPIError) as excinfo:
        with runtime_engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {ledger} WHERE id = :i"),
                {"i": row_id},
            )
    _assert_42501(excinfo.value)


@requires_pg
@pytest.mark.parametrize("ledger", LEDGERS)
def test_owner_update_still_succeeds(pg_engine, ledger):
    """Migration/owner path stays intact for approved schema surgery."""
    ids = seed_stores_and_catalog(pg_engine)
    row_id = _seed_ledger_row(pg_engine, ids, ledger)
    exec_sql(
        pg_engine,
        f"UPDATE {ledger} SET reason = 'owner surgery' WHERE id = :i",
        {"i": row_id},
    )
