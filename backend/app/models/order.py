"""orders, order_items, order_status_history models (migration 0004).

Fulfillment NEVER touches stock: nothing in these models mutates product
quantities. Order status history is an append-only ledger protected at the
database level (privileges.sql: runtime role gets SELECT/INSERT only).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk

_PAYMENT_STATUSES = (
    "('Unpaid','Pending','Paid','Failed','Refunded','Partially paid')"
)
_FULFILLMENT_STATUSES = (
    "('Unfulfilled','Processing','Partially fulfilled','Shipped','Delivered',"
    "'Cancelled','Returned')"
)


class Order(Base, UuidPk, Timestamped):
    __tablename__ = "orders"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Counter-allocated in the checkout transaction; gap-free, unique per store.
    # Format: 'ORD-' || lpad(n, 6, '0').
    order_number: Mapped[str] = mapped_column(String(20), nullable=False)
    # Nullable: guest checkout (guest carts convert to orders without a customer).
    customer_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Nullable: the originating cart; migration 0004 defines the PostgreSQL-only
    # column-list `ON DELETE SET NULL (cart_id)`.
    cart_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Flattened customer snapshot (survives customer changes).
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Unpaid", server_default="Unpaid"
    )
    fulfillment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Unfulfilled", server_default="Unfulfilled"
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Flattened shipping address (OrderAddress in the dashboard).
    ship_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    ship_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ship_city: Mapped[str] = mapped_column(String(255), nullable=False)
    ship_state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ship_postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    ship_country: Mapped[str] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="orders_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "customer_id"],
            ["customers.store_id", "customers.id"],
            ondelete="RESTRICT",
            name="orders_store_customer_fk",
        ),
        ForeignKeyConstraint(
            ["store_id", "cart_id"],
            ["carts.store_id", "carts.id"],
            ondelete="RESTRICT",  # authoritative: migration SET NULL (cart_id)
            name="orders_store_cart_fk",
        ),
        UniqueConstraint("store_id", "order_number", name="orders_store_number_unique"),
        # Composite-FK target for order_items / order_status_history.
        UniqueConstraint("store_id", "id", name="orders_store_id_unique"),
        CheckConstraint("subtotal >= 0", name="subtotal_nonnegative"),
        CheckConstraint("shipping_cost >= 0", name="shipping_nonnegative"),
        CheckConstraint("discount >= 0", name="discount_nonnegative"),
        CheckConstraint("total >= 0", name="total_nonnegative"),
        CheckConstraint(
            "total = subtotal + shipping_cost - discount", name="totals_arithmetic"
        ),
        CheckConstraint(
            f"payment_status IN {_PAYMENT_STATUSES}", name="payment_status_vocabulary"
        ),
        CheckConstraint(
            f"fulfillment_status IN {_FULFILLMENT_STATUSES}",
            name="fulfillment_status_vocabulary",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_alpha3",
        ),
        CheckConstraint("length(customer_email) > 0", name="customer_email_required"),
        CheckConstraint("length(ship_line1) BETWEEN 1 AND 255", name="ship_line1_length"),
        CheckConstraint("length(ship_city) BETWEEN 1 AND 255", name="ship_city_length"),
        CheckConstraint(
            "length(ship_postal_code) BETWEEN 1 AND 20", name="ship_postal_code_length"
        ),
        CheckConstraint(
            "length(ship_country) BETWEEN 2 AND 3", name="ship_country_length"
        ),
        Index("ix_orders_store_created_at", "store_id", "created_at"),
        Index("ix_orders_store_fulfillment_status", "store_id", "fulfillment_status"),
        Index("ix_orders_store_payment_status", "store_id", "payment_status"),
        Index("ix_orders_store_customer_email", "store_id", "customer_email"),
    )


class OrderItem(Base, UuidPk, Timestamped):
    __tablename__ = "order_items"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Nullable: product deletion nulls ONLY product_id (migration column-list
    # SET NULL); the snapshot below is never lost.
    product_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Immutable line snapshot.
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="order_items_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "order_id"],
            ["orders.store_id", "orders.id"],
            ondelete="CASCADE",
            name="order_items_store_order_fk",
        ),
        ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="RESTRICT",  # authoritative: migration SET NULL (product_id)
            name="order_items_store_product_fk",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint(
            "line_total = quantity * unit_price", name="line_total_arithmetic"
        ),
        CheckConstraint(
            "length(product_name) BETWEEN 1 AND 255", name="product_name_length"
        ),
        Index("ix_order_items_order_id", "order_id"),
    )


class OrderStatusHistory(Base, UuidPk, Timestamped):
    """Append-only audit trail (runtime role: SELECT/INSERT only)."""

    __tablename__ = "order_status_history"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="order_status_history_store_fk",
        ),
        ForeignKeyConstraint(
            ["store_id", "order_id"],
            ["orders.store_id", "orders.id"],
            ondelete="CASCADE",
            name="order_status_history_store_order_fk",
        ),
        # Real transitions only.
        CheckConstraint(
            "previous_status <> new_status", name="transition_changed"
        ),
        CheckConstraint("length(reason) >= 1", name="reason_required"),
        Index("ix_order_status_history_order_created", "order_id", "created_at"),
        Index("ix_order_status_history_store_created", "store_id", "created_at"),
    )
