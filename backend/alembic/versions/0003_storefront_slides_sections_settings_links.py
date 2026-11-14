"""Migration 0003 — storefront_slides, storefront_sections, storefront_settings,
storefront_footer_links.

Hand-written PostgreSQL DDL mirroring backend/app/models/storefront.py (source
of truth). The slides.target_category_id FK uses the PostgreSQL 15+ column-list
form `ON DELETE SET NULL (target_category_id)` — store_id is never nulled.
JSONB columns (sections.config, settings.theme/social_links) have no database
FK protection; same-store validation is API-layer only (approved ruling).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storefront_slides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("subtitle", sa.String(length=300), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=False),
        sa.Column("cta_url", sa.String(length=2048), nullable=True),
        sa.Column("cta_label", sa.String(length=100), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("target_category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true_()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="storefront_slides_store_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_slides"),
        # Hard cap of FOUR slides per store: position 1..4 + one per position.
        sa.CheckConstraint("position BETWEEN 1 AND 4", name="ck_storefront_slides_position_range"),
        sa.UniqueConstraint("store_id", "position", name="storefront_slides_position_unique"),
        sa.CheckConstraint(
            "image_url LIKE 'http://%' OR image_url LIKE 'https://%'",
            name="ck_storefront_slides_image_url_http_scheme",
        ),
        sa.CheckConstraint(
            "image_url ~ '^https?://'", name="ck_storefront_slides_image_url_format"
        ),
        sa.CheckConstraint(
            "cta_url IS NULL OR cta_url LIKE 'http://%' OR cta_url LIKE 'https://%'",
            name="ck_storefront_slides_cta_url_http_scheme",
        ),
        sa.CheckConstraint(
            "cta_url IS NULL OR cta_url ~ '^https?://'",
            name="ck_storefront_slides_cta_url_format",
        ),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 255", name="ck_storefront_slides_title_length"),
    )
    # Composite same-store FK with PostgreSQL 15+ column-list SET NULL.
    op.execute(
        """
        ALTER TABLE storefront_slides
        ADD CONSTRAINT storefront_slides_store_category_fk
        FOREIGN KEY (store_id, target_category_id)
        REFERENCES categories (store_id, id)
        ON DELETE SET NULL (target_category_id);
        """
    )
    op.create_index(
        "ix_storefront_slides_render",
        "storefront_slides",
        ["store_id", "is_active", "position"],
    )

    op.create_table(
        "storefront_sections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("subtitle", sa.String(length=300), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true_()),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="storefront_sections_store_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_sections"),
        sa.UniqueConstraint("store_id", "position", name="storefront_sections_position_unique"),
        sa.CheckConstraint("position >= 1", name="ck_storefront_sections_position_min"),
        sa.CheckConstraint(
            "section_type IN ('featured_products','category_grid','banner',"
            "'custom_text','testimonials')",
            name="ck_storefront_sections_section_type_vocabulary",
        ),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 255", name="ck_storefront_sections_title_length"
        ),
    )
    op.create_index(
        "ix_storefront_sections_render",
        "storefront_sections",
        ["store_id", "is_active", "position"],
    )
    op.create_index(
        "ix_storefront_sections_section_type", "storefront_sections", ["section_type"]
    )

    op.create_table(
        "storefront_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false_()),
        sa.Column("theme", postgresql.JSONB(), nullable=True),
        sa.Column("social_links", postgresql.JSONB(), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("primary_color", sa.String(length=7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="storefront_settings_store_fk"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_settings"),
        # store_id UNIQUE => exactly one settings row per store (1:1).
        sa.UniqueConstraint("store_id", name="uq_storefront_settings_store_id"),
        sa.CheckConstraint(
            "contact_email IS NULL OR (length(contact_email) >= 3 "
            "AND contact_email LIKE '%@%.%')",
            name="ck_storefront_settings_contact_email_shape",
        ),
        sa.CheckConstraint(
            "contact_email IS NULL OR contact_email ~ '^[^@]+@[^@]+\\.[^@]+$'",
            name="ck_storefront_settings_contact_email_format",
        ),
        sa.CheckConstraint(
            "primary_color IS NULL OR (length(primary_color) = 7 AND primary_color LIKE '#%')",
            name="ck_storefront_settings_primary_color_shape",
        ),
        sa.CheckConstraint(
            "primary_color IS NULL OR primary_color ~ '^#[0-9a-fA-F]{6}$'",
            name="ck_storefront_settings_primary_color_format",
        ),
    )

    op.create_table(
        "storefront_footer_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE",
            name="storefront_footer_links_store_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_footer_links"),
        sa.UniqueConstraint("store_id", "position", name="storefront_footer_links_position_unique"),
        sa.CheckConstraint("position >= 1", name="ck_storefront_footer_links_position_min"),
        sa.CheckConstraint(
            "length(label) BETWEEN 1 AND 100", name="ck_storefront_footer_links_label_length"
        ),
        sa.CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'",
            name="ck_storefront_footer_links_url_http_scheme",
        ),
        sa.CheckConstraint(
            "url ~ '^https?://'", name="ck_storefront_footer_links_url_format"
        ),
    )
    op.create_index(
        "ix_storefront_footer_links_store_position",
        "storefront_footer_links",
        ["store_id", "position"],
    )


def downgrade() -> None:
    # Reverse dependency order: children first; composite FK dropped
    # explicitly before its table.
    op.drop_index(
        "ix_storefront_footer_links_store_position", table_name="storefront_footer_links"
    )
    op.drop_table("storefront_footer_links")
    op.drop_table("storefront_settings")
    op.drop_index("ix_storefront_sections_section_type", table_name="storefront_sections")
    op.drop_index("ix_storefront_sections_render", table_name="storefront_sections")
    op.drop_table("storefront_sections")
    op.drop_index("ix_storefront_slides_render", table_name="storefront_slides")
    op.execute(
        "ALTER TABLE storefront_slides DROP CONSTRAINT IF EXISTS "
        "storefront_slides_store_category_fk;"
    )
    op.drop_table("storefront_slides")
