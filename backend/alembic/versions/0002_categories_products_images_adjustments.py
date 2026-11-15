"""Migration 0002 — categories, products, product_images, inventory_adjustments.

Hand-written PostgreSQL DDL mirroring backend/app/models/{category,product,
inventory_adjustment}.py (source of truth). The products.category_id FK uses
the PostgreSQL 15+ column-list form `ON DELETE SET NULL (category_id)` so ONLY
the data column is nulled on category deletion — store_id is never touched.
Slug/url regex CHECKs (PostgreSQL-only) carried here per the approved design.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("image", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="categories_store_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("store_id", "slug", name="categories_store_slug_unique"),
        sa.UniqueConstraint("store_id", "id", name="categories_store_id_unique"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 255", name="ck_categories_name_length"),
        sa.CheckConstraint("status IN ('Active','Draft')", name="ck_categories_status_vocabulary"),
        sa.CheckConstraint("slug = lower(slug)", name="ck_categories_slug_lowercase"),
        # Dashboard slug regex (resourceForm.ts:39) — PostgreSQL-only.
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_categories_slug_format"
        ),
    )
    op.create_index("ix_categories_store_status", "categories", ["store_id", "status"])

    op.create_table(
        "products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("image", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("stock_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
        sa.Column("inventory_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="products_store_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("store_id", "slug", name="products_store_slug_unique"),
        sa.UniqueConstraint("store_id", "sku", name="products_store_sku_unique"),
        sa.UniqueConstraint("store_id", "id", name="products_store_id_unique"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 255", name="ck_products_name_length"),
        sa.CheckConstraint("slug = lower(slug)", name="ck_products_slug_lowercase"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_products_slug_format"
        ),
        sa.CheckConstraint("price >= 0", name="ck_products_price_nonnegative"),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_products_stock_nonnegative"),
        sa.CheckConstraint(
            "low_stock_threshold >= 0", name="ck_products_low_stock_threshold_nonnegative"
        ),
        sa.CheckConstraint("status IN ('Active','Draft')", name="ck_products_status_vocabulary"),
    )
    # Composite same-store FK with PostgreSQL 15+ column-list SET NULL:
    # deleting a category nulls ONLY products.category_id (never store_id).
    op.execute(
        """
        ALTER TABLE products
        ADD CONSTRAINT products_store_category_fk
        FOREIGN KEY (store_id, category_id)
        REFERENCES categories (store_id, id)
        ON DELETE SET NULL (category_id);
        """
    )
    op.create_index("ix_products_store_status", "products", ["store_id", "status"])

    op.create_table(
        "product_images",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("alt", sa.String(length=255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="product_images_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"], ["products.store_id", "products.id"],
            ondelete="CASCADE", name="product_images_store_product_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_images"),
        sa.UniqueConstraint(
            "store_id", "product_id", "position", name="product_images_position_unique"
        ),
        sa.CheckConstraint("position >= 1", name="ck_product_images_position_min"),
        sa.CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'",
            name="ck_product_images_url_http_scheme",
        ),
        sa.CheckConstraint(
            "url ~ '^https?://'", name="ck_product_images_url_format"
        ),
    )

    op.create_table(
        "inventory_adjustments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("adjustment_amount", sa.Integer(), nullable=False),
        sa.Column("previous_quantity", sa.Integer(), nullable=False),
        sa.Column("new_quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="inventory_adjustments_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"], ["products.store_id", "products.id"],
            ondelete="RESTRICT", name="inventory_adjustments_store_product_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_adjustments"),
        sa.CheckConstraint(
            "previous_quantity >= 0", name="previous_quantity_nonnegative"
        ),
        sa.CheckConstraint(
            "new_quantity >= 0", name="new_quantity_nonnegative"
        ),
        sa.CheckConstraint(
            "new_quantity = previous_quantity + adjustment_amount",
            name="adjustment_arithmetic",
        ),
        sa.CheckConstraint("length(reason) >= 1", name="reason_required"),
    )
    op.create_index(
        "ix_inventory_adjustments_store_product_occurred",
        "inventory_adjustments",
        ["store_id", "product_id", "occurred_at"],
    )
    op.create_index(
        "ix_inventory_adjustments_store_occurred",
        "inventory_adjustments",
        ["store_id", "occurred_at"],
    )


def downgrade() -> None:
    # Reverse dependency order: children first, composite FKs dropped
    # explicitly before their tables.
    op.drop_index(
        "ix_inventory_adjustments_store_occurred", table_name="inventory_adjustments"
    )
    op.drop_index(
        "ix_inventory_adjustments_store_product_occurred",
        table_name="inventory_adjustments",
    )
    op.drop_table("inventory_adjustments")
    op.drop_table("product_images")
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_store_category_fk;")
    op.drop_index("ix_products_store_status", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_categories_store_status", table_name="categories")
    op.drop_table("categories")
