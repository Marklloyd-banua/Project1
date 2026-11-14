"""Migration 0004 — customers, customer_addresses, carts, cart_items, orders,
order_items, order_status_history.

Hand-written PostgreSQL DDL mirroring backend/app/models/{customer,cart,
order}.py (source of truth). Two PostgreSQL 15+ column-list SET NULL FKs:
orders.cart_id and order_items.product_id — ONLY the data column is nulled;
store_id and order snapshots are never touched. Append-only ledgers
(inventory_adjustments in 0002, order_status_history here) get runtime-role
protection via backend/db/privileges.sql, NOT via this migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="customers_store_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("store_id", "email", name="customers_store_email_unique"),
        sa.UniqueConstraint("store_id", "id", name="customers_store_id_unique"),
        sa.CheckConstraint("email = lower(email)", name="ck_customers_email_lowercase"),
        sa.CheckConstraint("status IN ('Active','Suspended')", name="ck_customers_status_vocabulary"),
        sa.CheckConstraint(
            "email ~ '^[^@]+@[^@]+\\.[^@]+$'", name="ck_customers_email_format"
        ),
    )
    op.create_index("ix_customers_store_status", "customers", ["store_id", "status"])

    op.create_table(
        "customer_addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("line1", sa.String(length=255), nullable=False),
        sa.Column("line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("country", sa.String(length=3), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="customer_addresses_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "customer_id"], ["customers.store_id", "customers.id"],
            ondelete="CASCADE", name="customer_addresses_store_customer_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customer_addresses"),
        sa.CheckConstraint("length(line1) BETWEEN 1 AND 255", name="ck_customer_addresses_line1_length"),
        sa.CheckConstraint("length(city) BETWEEN 1 AND 255", name="ck_customer_addresses_city_length"),
        sa.CheckConstraint(
            "length(postal_code) BETWEEN 1 AND 20", name="ck_customer_addresses_postal_code_length"
        ),
        sa.CheckConstraint(
            "length(country) BETWEEN 2 AND 3", name="ck_customer_addresses_country_length"
        ),
    )
    # One default address per customer (partial unique index).
    op.create_index(
        "uq_default_address_per_customer",
        "customer_addresses",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "carts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guest_token", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="carts_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "customer_id"], ["customers.store_id", "customers.id"],
            ondelete="RESTRICT", name="carts_store_customer_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_carts"),
        sa.UniqueConstraint("store_id", "id", name="carts_store_id_unique"),
        sa.UniqueConstraint("guest_token", name="uq_carts_guest_token"),
        # Guest XOR customer identity.
        sa.CheckConstraint(
            "(customer_id IS NULL AND guest_token IS NOT NULL) "
            "OR (customer_id IS NOT NULL AND guest_token IS NULL)",
            name="ck_carts_guest_xor_customer",
        ),
        sa.CheckConstraint(
            "status IN ('active','converted','abandoned')",
            name="ck_carts_status_vocabulary",
        ),
    )
    # One ACTIVE cart per customer (per store).
    op.create_index(
        "uq_active_cart_per_customer",
        "carts",
        ["store_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND customer_id IS NOT NULL"),
    )
    op.create_index("ix_carts_store_status", "carts", ["store_id", "status"])

    op.create_table(
        "cart_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cart_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="cart_items_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "cart_id"], ["carts.store_id", "carts.id"],
            ondelete="CASCADE", name="cart_items_store_cart_fk",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"], ["products.store_id", "products.id"],
            ondelete="RESTRICT", name="cart_items_store_product_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cart_items"),
        sa.UniqueConstraint("cart_id", "product_id", name="cart_items_cart_product_unique"),
        sa.CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_cart_items_unit_price_nonnegative"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])

    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cart_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=False),
        sa.Column("customer_phone", sa.String(length=50), nullable=True),
        sa.Column("payment_status", sa.String(length=20), nullable=False, server_default="Unpaid"),
        sa.Column("fulfillment_status", sa.String(length=20), nullable=False, server_default="Unfulfilled"),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("shipping_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("ship_line1", sa.String(length=255), nullable=False),
        sa.Column("ship_line2", sa.String(length=255), nullable=True),
        sa.Column("ship_city", sa.String(length=255), nullable=False),
        sa.Column("ship_state", sa.String(length=255), nullable=True),
        sa.Column("ship_postal_code", sa.String(length=20), nullable=False),
        sa.Column("ship_country", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="orders_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "customer_id"], ["customers.store_id", "customers.id"],
            ondelete="RESTRICT", name="orders_store_customer_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("store_id", "order_number", name="orders_store_number_unique"),
        sa.UniqueConstraint("store_id", "id", name="orders_store_id_unique"),
        sa.CheckConstraint("subtotal >= 0", name="ck_orders_subtotal_nonnegative"),
        sa.CheckConstraint("shipping_cost >= 0", name="ck_orders_shipping_nonnegative"),
        sa.CheckConstraint("discount >= 0", name="ck_orders_discount_nonnegative"),
        sa.CheckConstraint("total >= 0", name="ck_orders_total_nonnegative"),
        sa.CheckConstraint(
            "total = subtotal + shipping_cost - discount",
            name="ck_orders_totals_arithmetic",
        ),
        sa.CheckConstraint(
            "payment_status IN ('Unpaid','Pending','Paid','Failed','Refunded',"
            "'Partially paid')",
            name="ck_orders_payment_status_vocabulary",
        ),
        sa.CheckConstraint(
            "fulfillment_status IN ('Unfulfilled','Processing','Partially fulfilled',"
            "'Shipped','Delivered','Cancelled','Returned')",
            name="ck_orders_fulfillment_status_vocabulary",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_orders_currency_iso_alpha3",
        ),
        sa.CheckConstraint(
            "length(customer_email) > 0", name="ck_orders_customer_email_required"
        ),
        sa.CheckConstraint(
            "customer_email ~ '^[^@]+@[^@]+\\.[^@]+$'",
            name="ck_orders_customer_email_format",
        ),
        sa.CheckConstraint(
            "length(ship_line1) BETWEEN 1 AND 255", name="ck_orders_ship_line1_length"
        ),
        sa.CheckConstraint(
            "length(ship_city) BETWEEN 1 AND 255", name="ck_orders_ship_city_length"
        ),
        sa.CheckConstraint(
            "length(ship_postal_code) BETWEEN 1 AND 20",
            name="ck_orders_ship_postal_code_length",
        ),
        sa.CheckConstraint(
            "length(ship_country) BETWEEN 2 AND 3", name="ck_orders_ship_country_length"
        ),
    )
    # Composite same-store FK with PostgreSQL 15+ column-list SET NULL:
    # deleting a cart nulls ONLY orders.cart_id (never store_id).
    op.execute(
        """
        ALTER TABLE orders
        ADD CONSTRAINT orders_store_cart_fk
        FOREIGN KEY (store_id, cart_id)
        REFERENCES carts (store_id, id)
        ON DELETE SET NULL (cart_id);
        """
    )
    op.create_index("ix_orders_store_created_at", "orders", ["store_id", "created_at"])
    op.create_index(
        "ix_orders_store_fulfillment_status", "orders", ["store_id", "fulfillment_status"]
    )
    op.create_index(
        "ix_orders_store_payment_status", "orders", ["store_id", "payment_status"]
    )
    op.create_index(
        "ix_orders_store_customer_email", "orders", ["store_id", "customer_email"]
    )

    op.create_table(
        "order_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("product_sku", sa.String(length=100), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="order_items_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "order_id"], ["orders.store_id", "orders.id"],
            ondelete="CASCADE", name="order_items_store_order_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_nonnegative"),
        sa.CheckConstraint(
            "line_total = quantity * unit_price", name="ck_order_items_line_total_arithmetic"
        ),
        sa.CheckConstraint(
            "length(product_name) BETWEEN 1 AND 255", name="ck_order_items_product_name_length"
        ),
    )
    # Composite same-store FK with PostgreSQL 15+ column-list SET NULL:
    # deleting a product nulls ONLY order_items.product_id; the snapshot
    # (product_name, product_sku, unit_price) is preserved.
    op.execute(
        """
        ALTER TABLE order_items
        ADD CONSTRAINT order_items_store_product_fk
        FOREIGN KEY (store_id, product_id)
        REFERENCES products (store_id, id)
        ON DELETE SET NULL (product_id);
        """
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    op.create_table(
        "order_status_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=False),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="order_status_history_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "order_id"], ["orders.store_id", "orders.id"],
            ondelete="CASCADE", name="order_status_history_store_order_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_status_history"),
        sa.CheckConstraint(
            "previous_status <> new_status", name="ck_order_status_history_transition_changed"
        ),
        sa.CheckConstraint(
            "length(reason) >= 1", name="ck_order_status_history_reason_required"
        ),
    )
    op.create_index(
        "ix_order_status_history_order_created",
        "order_status_history",
        ["order_id", "created_at"],
    )
    op.create_index(
        "ix_order_status_history_store_created",
        "order_status_history",
        ["store_id", "created_at"],
    )


def downgrade() -> None:
    # Reverse dependency order: history -> items -> orders -> carts ->
    # addresses -> customers; composite FKs dropped explicitly first.
    op.drop_index(
        "ix_order_status_history_store_created", table_name="order_status_history"
    )
    op.drop_index(
        "ix_order_status_history_order_created", table_name="order_status_history"
    )
    op.drop_table("order_status_history")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.execute(
        "ALTER TABLE order_items DROP CONSTRAINT IF EXISTS order_items_store_product_fk;"
    )
    op.drop_table("order_items")
    op.drop_index("ix_orders_store_customer_email", table_name="orders")
    op.drop_index("ix_orders_store_payment_status", table_name="orders")
    op.drop_index("ix_orders_store_fulfillment_status", table_name="orders")
    op.drop_index("ix_orders_store_created_at", table_name="orders")
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_store_cart_fk;")
    op.drop_table("orders")
    op.drop_index("ix_carts_store_status", table_name="carts")
    op.drop_index("uq_active_cart_per_customer", table_name="carts")
    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_index("uq_default_address_per_customer", table_name="customer_addresses")
    op.drop_table("customer_addresses")
    op.drop_index("ix_customers_store_status", table_name="customers")
    op.drop_table("customers")
