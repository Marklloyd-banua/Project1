"""Phase 2 constraint tests (PostgreSQL-only; disposable migrated database).

Exercises the approved database invariants end-to-end on PostgreSQL:
same-store composite FK isolation, CHECK vocabularies and arithmetic,
partial unique indexes, column-list SET NULL behavior (category/product
deletion nulls ONLY the data column), and RESTRICT history preservation.
"""

from __future__ import annotations

import uuid

from tests.conftest import (
    exec_sql,
    expect_error,
    pg_engine,  # noqa: F401 (fixture)
    requires_pg,
    seed_stores_and_catalog,
)


@requires_pg
def test_cross_store_category_reference_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO products (store_id, name, slug, price, stock_quantity, "
        "category_id) VALUES (:s, 'X', 'x', 1.00, 0, :c)",
        {"s": ids["store_b"], "c": ids["category_a"]},
        match="product_images|foreign key|violates",  # FK violation surfaces
    )


@requires_pg
def test_cross_store_cart_product_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    cart = exec_sql(
        pg_engine,
        "INSERT INTO carts (store_id, guest_token) VALUES (:s, :t) RETURNING id",
        {"s": ids["store_b"], "t": f"guest-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    expect_error(
        pg_engine,
        "INSERT INTO cart_items (store_id, cart_id, product_id, quantity, "
        "unit_price) VALUES (:s, :c, :p, 1, 1.00)",
        {"s": ids["store_b"], "c": cart, "p": ids["product_a"]},
    )


@requires_pg
def test_invalid_payment_status_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, payment_status, subtotal, shipping_cost, discount, "
        "total, currency, ship_line1, ship_city, ship_postal_code, "
        "ship_country) VALUES (:s, 'ORD-000001', 'C', 'c@example.com', "
        "'Settled', 0, 0, 0, 0, 'USD', 'L', 'C', '123', 'US')",
        {"s": ids["store_a"]},
        match="payment_status_vocabulary",
    )


@requires_pg
def test_invalid_fulfillment_status_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, fulfillment_status, subtotal, shipping_cost, "
        "discount, total, currency, ship_line1, ship_city, ship_postal_code, "
        "ship_country) VALUES (:s, 'ORD-000002', 'C', 'c@example.com', "
        "'Pending', 0, 0, 0, 0, 'USD', 'L', 'C', '123', 'US')",
        {"s": ids["store_a"]},
        match="fulfillment_status_vocabulary",
    )


@requires_pg
def test_order_totals_arithmetic_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, 'ORD-000003', 'C', 'c@example.com', 10.00, 2.00, 1.00, "
        "12.00, 'USD', 'L', 'C', '123', 'US')",
        {"s": ids["store_a"]},
        match="totals_arithmetic",
    )


@requires_pg
def test_order_line_total_arithmetic_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    order = exec_sql(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, 'ORD-000004', 'C', 'c@example.com', 10.00, 0, 0, 10.00, "
        "'USD', 'L', 'C', '123', 'US') RETURNING id",
        {"s": ids["store_a"]},
    ).scalar_one()
    expect_error(
        pg_engine,
        "INSERT INTO order_items (store_id, order_id, product_id, "
        "product_name, quantity, unit_price, line_total) "
        "VALUES (:s, :o, :p, 'Tee', 2, 5.00, 9.00)",
        {"s": ids["store_a"], "o": order, "p": ids["product_a"]},
        match="line_total_arithmetic",
    )


@requires_pg
def test_adjustment_arithmetic_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO inventory_adjustments (store_id, product_id, "
        "adjustment_amount, previous_quantity, new_quantity, reason) "
        "VALUES (:s, :p, 2, 5, 8, 'restock')",
        {"s": ids["store_a"], "p": ids["product_a"]},
        match="adjustment_arithmetic",
    )


@requires_pg
def test_negative_new_quantity_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO inventory_adjustments (store_id, product_id, "
        "adjustment_amount, previous_quantity, new_quantity, reason) "
        "VALUES (:s, :p, -10, 5, -5, 'oops')",
        {"s": ids["store_a"], "p": ids["product_a"]},
        match="new_quantity_nonnegative",
    )


@requires_pg
def test_slide_position_5_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO storefront_slides (store_id, title, image_url, position) "
        "VALUES (:s, 'S5', 'https://x.test/i.png', 5)",
        {"s": ids["store_a"]},
        match="position_range",
    )


@requires_pg
def test_cart_identity_xor_violations_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    customer = exec_sql(
        pg_engine,
        "INSERT INTO customers (store_id, email, full_name) "
        "VALUES (:s, :e, 'C') RETURNING id",
        {"s": ids["store_a"], "e": f"c-{uuid.uuid4().hex[:8]}@example.com"},
    ).scalar_one()
    # Both identities -> rejected
    expect_error(
        pg_engine,
        "INSERT INTO carts (store_id, customer_id, guest_token) "
        "VALUES (:s, :c, 'tok')",
        {"s": ids["store_a"], "c": customer},
        match="guest_xor_customer",
    )
    # Neither identity -> rejected
    expect_error(
        pg_engine,
        "INSERT INTO carts (store_id) VALUES (:s)",
        {"s": ids["store_a"]},
        match="guest_xor_customer",
    )


@requires_pg
def test_second_owner_per_store_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    exec_sql(
        pg_engine,
        "INSERT INTO store_memberships (store_id, staff_user_id, role) "
        "VALUES (:s, :u, 'owner')",
        {"s": ids["store_a"], "u": ids["staff_id"]},
    )
    second = exec_sql(
        pg_engine,
        "INSERT INTO staff_users (email, full_name) VALUES (:e, 'B') RETURNING id",
        {"e": f"second-{uuid.uuid4().hex[:8]}@example.com"},
    ).scalar_one()
    expect_error(
        pg_engine,
        "INSERT INTO store_memberships (store_id, staff_user_id, role) "
        "VALUES (:s, :u, 'owner')",
        {"s": ids["store_a"], "u": second},
        match="uq_one_owner_per_store",
    )


@requires_pg
def test_second_active_cart_per_customer_rejected(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    customer = exec_sql(
        pg_engine,
        "INSERT INTO customers (store_id, email, full_name) "
        "VALUES (:s, :e, 'C') RETURNING id",
        {"s": ids["store_a"], "e": f"ac-{uuid.uuid4().hex[:8]}@example.com"},
    ).scalar_one()
    exec_sql(
        pg_engine,
        "INSERT INTO carts (store_id, customer_id) VALUES (:s, :c)",
        {"s": ids["store_a"], "c": customer},
    )
    expect_error(
        pg_engine,
        "INSERT INTO carts (store_id, customer_id) VALUES (:s, :c)",
        {"s": ids["store_a"], "c": customer},
        match="uq_active_cart_per_customer",
    )


@requires_pg
def test_category_delete_nulls_category_id_preserves_text_and_store(pg_engine):
    """Column-list SET NULL: ONLY products.category_id is nulled; the category
    TEXT and store_id are untouched."""
    ids = seed_stores_and_catalog(pg_engine)
    exec_sql(pg_engine, "DELETE FROM categories WHERE id = :c", {"c": ids["category_a"]})
    row = exec_sql(
        pg_engine,
        "SELECT category_id, category, store_id FROM products WHERE id = :p",
        {"p": ids["product_a"]},
    ).fetchone()
    assert row.category_id is None, "only category_id must be nulled"
    assert row.category == "Clothing", "category TEXT is a preserved display cache"
    assert row.store_id == ids["store_a"], "store_id must NEVER be nulled"


@requires_pg
def test_product_delete_nulls_order_item_product_preserves_snapshot(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    order = exec_sql(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, 'ORD-000005', 'C', 'c@example.com', 10.00, 0, 0, 10.00, "
        "'USD', 'L', 'C', '123', 'US') RETURNING id",
        {"s": ids["store_a"]},
    ).scalar_one()
    exec_sql(
        pg_engine,
        "INSERT INTO order_items (store_id, order_id, product_id, "
        "product_name, product_sku, quantity, unit_price, line_total) "
        "VALUES (:s, :o, :p, 'Tee', 'TEE-1', 1, 10.00, 10.00)",
        {"s": ids["store_a"], "o": order, "p": ids["product_a"]},
    )
    exec_sql(pg_engine, "DELETE FROM products WHERE id = :p", {"p": ids["product_a"]})
    item = exec_sql(
        pg_engine,
        "SELECT product_id, product_name, product_sku, unit_price, quantity "
        "FROM order_items WHERE order_id = :o",
        {"o": order},
    ).fetchone()
    assert item.product_id is None, "only product_id must be nulled"
    assert item.product_name == "Tee"
    assert item.product_sku == "TEE-1"
    assert str(item.unit_price) == "10.00"
    assert item.quantity == 1


@requires_pg
def test_product_with_cart_item_cannot_be_deleted(pg_engine):
    """cart_items RESTRICT: product removal from carts is explicit."""
    ids = seed_stores_and_catalog(pg_engine)
    cart = exec_sql(
        pg_engine,
        "INSERT INTO carts (store_id, guest_token) VALUES (:s, :t) RETURNING id",
        {"s": ids["store_a"], "t": f"g-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    exec_sql(
        pg_engine,
        "INSERT INTO cart_items (store_id, cart_id, product_id, quantity, "
        "unit_price) VALUES (:s, :c, :p, 1, 10.00)",
        {"s": ids["store_a"], "c": cart, "p": ids["product_a"]},
    )
    expect_error(
        pg_engine,
        "DELETE FROM products WHERE id = :p",
        {"p": ids["product_a"]},
        match="cart_items_store_product_fk|restrict",
    )


@requires_pg
def test_product_with_adjustment_history_cannot_be_deleted(pg_engine):
    """Ledger RESTRICT: inventory history is never cascaded away."""
    ids = seed_stores_and_catalog(pg_engine)
    exec_sql(
        pg_engine,
        "INSERT INTO inventory_adjustments (store_id, product_id, "
        "adjustment_amount, previous_quantity, new_quantity, reason) "
        "VALUES (:s, :p, -2, 5, 3, 'sale')",
        {"s": ids["store_a"], "p": ids["product_a"]},
    )
    expect_error(
        pg_engine,
        "DELETE FROM products WHERE id = :p",
        {"p": ids["product_a"]},
        match="inventory_adjustments_store_product_fk|restrict",
    )


@requires_pg
def test_lowercase_email_and_currency_checks_enforced(pg_engine):
    ids = seed_stores_and_catalog(pg_engine)
    expect_error(
        pg_engine,
        "INSERT INTO customers (store_id, email, full_name) "
        "VALUES (:s, 'Upper@Example.com', 'X')",
        {"s": ids["store_a"]},
        match="email_lowercase",
    )
    expect_error(
        pg_engine,
        "INSERT INTO orders (store_id, order_number, customer_name, "
        "customer_email, subtotal, shipping_cost, discount, total, currency, "
        "ship_line1, ship_city, ship_postal_code, ship_country) "
        "VALUES (:s, 'ORD-000006', 'C', 'c@example.com', 0, 0, 0, 0, "
        "'usd', 'L', 'C', '123', 'US')",
        {"s": ids["store_a"]},
        match="currency_iso_alpha3",
    )
