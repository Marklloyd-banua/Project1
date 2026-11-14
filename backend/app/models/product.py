"""products, product_images models (migration 0002)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk


class Product(Base, UuidPk, Timestamped):
    __tablename__ = "products"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # category_id is AUTHORITATIVE for linked products (storefront filtering is
    # id-based). The migration 0002 FK defines the PostgreSQL-only column-list
    # `ON DELETE SET NULL (category_id)`; the metadata FK here is the portable
    # RESTRICT approximation (category deletion in metadata-created DBs raises
    # instead of nulling).
    category_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Display cache for dashboard compatibility; rewritten transactionally on
    # category rename. Legacy unmatched rows keep this text with category_id NULL.
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Primary image URL (dashboard StoreProduct.image).
    image: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Active", server_default="Active"
    )
    inventory_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="products_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "category_id"],
            ["categories.store_id", "categories.id"],
            ondelete="RESTRICT",  # authoritative: migration SET NULL (category_id)
            name="products_store_category_fk",
        ),
        UniqueConstraint("store_id", "slug", name="products_store_slug_unique"),
        # NULL skus never collide (SQL NULLs are distinct in SQL unique indexes).
        UniqueConstraint("store_id", "sku", name="products_store_sku_unique"),
        # Composite-FK target for cart_items / inventory_adjustments / order_items.
        UniqueConstraint("store_id", "id", name="products_store_id_unique"),
        CheckConstraint("length(name) BETWEEN 1 AND 255", name="name_length"),
        CheckConstraint("slug = lower(slug)", name="slug_lowercase"),
        CheckConstraint("price >= 0", name="price_nonnegative"),
        CheckConstraint("stock_quantity >= 0", name="stock_nonnegative"),
        CheckConstraint(
            "low_stock_threshold >= 0", name="low_stock_threshold_nonnegative"
        ),
        CheckConstraint("status IN ('Active','Draft')", name="status_vocabulary"),
        Index("ix_products_store_status", "store_id", "status"),
    )


class ProductImage(Base, UuidPk, Timestamped):
    __tablename__ = "product_images"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    alt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="product_images_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="CASCADE",
            name="product_images_store_product_fk",
        ),
        UniqueConstraint(
            "store_id", "product_id", "position", name="product_images_position_unique"
        ),
        CheckConstraint("position >= 1", name="position_min"),
        CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'",
            name="url_http_scheme",
        ),
    )
