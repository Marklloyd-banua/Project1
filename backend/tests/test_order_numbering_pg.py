"""Phase 2 order-numbering tests (PostgreSQL-only; disposable database).

Verifies the approved counter strategy: trigger-initialized at 0, row-lock
allocation producing gap-free per-store numbers, and per-store uniqueness of
the allocated order number.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from tests.conftest import (
    exec_sql,
    expect_error,
    pg_engine,  # noqa: F401 (fixture)
    requires_pg,
    seed_stores_and_catalog,
)


def allocate_order_number(engine, store_id) -> str:
    """The approved allocation pattern (Phase 3 will reuse it verbatim):
    one transaction, row-locked counter read, +1 update, commit."""
    with engine.begin() as conn:
        current = conn.execute(
            text(
                "SELECT last_order_number FROM store_order_counters "
                "WHERE store_id = :s FOR UPDATE"
            ),
            {"s": store_id},
        ).scalar_one()
        next_number = current + 1
        conn.execute(
            text(
                "UPDATE store_order_counters SET last_order_number = :n "
                "WHERE store_id = :s"
            ),
            {"n": next_number, "s": store_id},
        )
    from sqlalchemy import text as _text  # noqa: F401 (kept local for clarity)

    return f"ORD-{next_number:06d}"


from sqlalchemy import text  # noqa: E402


@requires_pg
def test_counter_starts_at_zero_and_first_number_is_one(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    counter = exec_sql(
        pg_engine,
        "SELECT last_order_number FROM store_order_counters WHERE store_id = :s",
        {"s": ids["store_a"]},
    ).scalar_one()
    assert counter == 0, "trigger initializes the counter at 0"
    assert allocate_order_number(pg_engine, ids["store_a"]) == "ORD-000001"


@requires_pg
def test_allocation_is_gap_free_per_store(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    numbers = [
        allocate_order_number(pg_engine, ids["store_a"]) for _ in range(3)
    ]
    assert numbers == ["ORD-000001", "ORD-000002", "ORD-000003"]
    # Other stores are unaffected (per-store counters).
    other = allocate_order_number(pg_engine, ids["store_b"])
    assert other == "ORD-000001"


@requires_pg
def test_order_number_unique_per_store(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    exec_sql(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, 'ORD-000001', 'C', 'c@example.com', 0, 0, 0, 0, 'USD', "
        "'L', 'C', '123', 'US')",
        {"s": ids["store_a"]},
    )
    expect_error(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, 'ORD-000001', 'C2', 'c2@example.com', 0, 0, 0, 0, "
        "'USD', 'L', 'C', '123', 'US')",
        {"s": ids["store_a"]},
        match="orders_store_number_unique",
    )


@requires_pg
def test_allocated_number_acceptable_and_unique_check_together(pg_engine):
    """End-to-end: allocate, then insert the order with that number."""
    ids = seed_stores_and_catalog(pg_engine)
    number = allocate_order_number(pg_engine, ids["store_a"])
    exec_sql(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, :n, 'C', 'c@example.com', 0, 0, 0, 0, 'USD', "
        "'L', 'C', '123', 'US')",
        {"s": ids["store_a"], "n": number},
    )
    duplicate = allocate_order_number(pg_engine, ids["store_a"])
    assert duplicate != number


@requires_pg
def test_concurrent_allocation_same_store_no_duplicates_gap_free_and_independent(pg_engine):
    """Real multi-connection allocation: same-store concurrency is serialized by
    the row lock, producing unique, gap-free numbers; stores are independent."""
    ids = seed_stores_and_catalog(pg_engine)

    def allocate_concurrently(store_id, count: int) -> list[str]:
        barrier = threading.Barrier(count)
        numbers: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            # Deterministic synchronization: all workers reach the barrier, then
            # each performs the approved allocation in its own transaction/connection.
            barrier.wait()
            with pg_engine.begin() as conn:
                current = conn.execute(
                    text(
                        "SELECT last_order_number FROM store_order_counters "
                        "WHERE store_id = :s FOR UPDATE"
                    ),
                    {"s": store_id},
                ).scalar_one()
                next_number = current + 1
                conn.execute(
                    text(
                        "UPDATE store_order_counters SET last_order_number = :n "
                        "WHERE store_id = :s"
                    ),
                    {"n": next_number, "s": store_id},
                )
            formatted = f"ORD-{next_number:06d}"
            with lock:
                numbers.append(formatted)

        with ThreadPoolExecutor(max_workers=count) as executor:
            futures = [executor.submit(worker) for _ in range(count)]
            for future in futures:
                future.result()  # propagate any allocation failure
        return numbers

    # Same store: bounded concurrent allocations -> unique and gap-free.
    n_a = 10
    numbers_a = allocate_concurrently(ids["store_a"], n_a)
    assert len(numbers_a) == n_a
    assert len(set(numbers_a)) == n_a, "concurrent allocations must not duplicate"
    expected_a = {f"ORD-{i:06d}" for i in range(1, n_a + 1)}
    assert set(numbers_a) == expected_a, "allocations must be gap-free when all succeed"

    # Different store maintains an independent counter (concurrent, starts at 1).
    n_b = 6
    numbers_b = allocate_concurrently(ids["store_b"], n_b)
    assert len(set(numbers_b)) == n_b
    expected_b = {f"ORD-{i:06d}" for i in range(1, n_b + 1)}
    assert set(numbers_b) == expected_b, "store counters must be independent"
