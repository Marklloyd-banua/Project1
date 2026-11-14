"""carts, cart_items models (migration 0004)."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk


class Cart(Base, UuidPk, Timestamped):
    __tablename__ = "carts"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Exactly one of the two identities: guest token XOR authenticated customer.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    guest_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="carts_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "customer_id"],
            ["customers.store_id", "customers.id"],
            ondelete="RESTRICT",  # customers soft-delete; never orphan an authed cart
            name="carts_store_customer_fk",
        ),
        # Composite-FK target for cart_items and orders.cart_id.
        UniqueConstraint("store_id", "id", name="carts_store_id_unique"),
        # Guest XOR customer identity.
        CheckConstraint(
            "(customer_id IS NULL AND guest_token IS NOT NULL) "
            "OR (customer_id IS NOT NULL AND guest_token IS NULL)",
            name="guest_xor_customer",
        ),
        CheckConstraint(
            "status IN ('active','converted','abandoned')", name="status_vocabulary"
        ),
        # One ACTIVE cart per customer (per store).
        Index(
            "uq_active_cart_per_customer",
            "store_id",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'active' AND customer_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND customer_id IS NOT NULL"),
        ),
        Index("ix_carts_store_status", "store_id", "status"),
    )


class CartItem(Base, UuidPk, Timestamped):
    __tablename__ = "cart_items"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cart_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Product removal from carts is explicit, never implicit (RESTRICT).
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Price captured at add-to-cart time; refreshed by the API on checkout.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="cart_items_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "cart_id"],
            ["carts.store_id", "carts.id"],
            ondelete="CASCADE",
            name="cart_items_store_cart_fk",
        ),
        ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="RESTRICT",
            name="cart_items_store_product_fk",
        ),
        UniqueConstraint("cart_id", "product_id", name="cart_items_cart_product_unique"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        Index("ix_cart_items_cart_id", "cart_id"),
    )
