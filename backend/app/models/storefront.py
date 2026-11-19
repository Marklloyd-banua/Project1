"""Storefront models (migrations 0003, 0005): slides, sections, settings, footer links.

JSONB columns (sections.config, settings.theme/social_links) are validated at
the API layer only — no database FKs can protect JSONB-embedded references
(approved ruling).

Migration 0005 (category-driven hero foundation) evolves storefront_slides:
- removes legacy max-4 position cap (retains position >= 1 and UNIQUE(store_id, position))
- adds authoritative category mapping (category_id, nullable for unmappable legacy rows)
- adds featured_product_id (nullable) and admin_is_enabled (preserves admin intent)
- adds composite FKs for same-store category/product integrity
- enforces uniqueness for mapped (store_id, category_id) rows while allowing unmapped legacy rows

Legacy columns/fields (including target_category_id and is_active) remain for B1.5B/B1.6
compatibility.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Boolean,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk

# Portable JSON that renders as JSONB on PostgreSQL.
JsonVar = JSON().with_variant(JSONB(), "postgresql")

_SECTION_TYPES = (
    "('featured_products','category_grid','banner','custom_text','testimonials')"
)


class StorefrontSlide(Base, UuidPk, Timestamped):
    __tablename__ = "storefront_slides"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    cta_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    cta_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Legacy optional same-store category link; migration 0003 defines PostgreSQL
    # column-list `ON DELETE SET NULL (target_category_id)`.
    target_category_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 0005: authoritative category mapping (nullable for unmappable legacy compatibility rows).
    category_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, default=None)
    # 0005: manual featured product selection (same store/category validated in service logic).
    featured_product_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, default=None)
    # 0005: preserves administrative intent when a mapping is temporarily ineligible/omitted publicly.
    admin_is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="storefront_slides_store_fk"
        ),
        ForeignKeyConstraint(
            ["store_id", "target_category_id"],
            ["categories.store_id", "categories.id"],
            ondelete="RESTRICT",  # authoritative: migration SET NULL (target_category_id)
            name="storefront_slides_store_category_fk",
        ),
        # 0005: authoritative mapping FK (category delete removes mapping row).
        ForeignKeyConstraint(
            ["store_id", "category_id"],
            ["categories.store_id", "categories.id"],
            ondelete="CASCADE",
            name="storefront_slides_store_category_mapping_fk",
        ),
        # 0005: featured product FK.
        # Dialect limitation: PostgreSQL requires column-list SET NULL to clear only
        # featured_product_id (`ON DELETE SET NULL (featured_product_id)`) while preserving
        # store_id/category_id/mapping/admin intent. Generic SQLAlchemy metadata cannot
        # express this portably, so no `ondelete` is declared here to avoid falsely claiming
        # ordinary composite SET NULL. Alembic migration 0005 is authoritative for the actual
        # PostgreSQL FK/delete behavior.
        ForeignKeyConstraint(
            ["store_id", "featured_product_id"],
            ["products.store_id", "products.id"],
            name="storefront_slides_store_featured_product_fk",
        ),
        # Owner-controlled ordering (unique per store); positions normalized transaction-safely.
        UniqueConstraint("store_id", "position", name="storefront_slides_position_unique"),
        # Uniqueness for mapped rows only: NULL category_id (unmapped legacy rows) may repeat
        # per store under standard UNIQUE NULL semantics (portable PostgreSQL/SQLite).
        UniqueConstraint(
            "store_id",
            "category_id",
            name="uq_storefront_slides_store_category_mapping",
        ),
        # Legacy max-4 cap removed in 0005; minimum retained.
        CheckConstraint("position >= 1", name="position_min"),
        CheckConstraint(
            "image_url LIKE 'http://%' OR image_url LIKE 'https://%'",
            name="image_url_http_scheme",
        ),
        CheckConstraint(
            "cta_url IS NULL OR cta_url LIKE 'http://%' OR cta_url LIKE 'https://%'",
            name="cta_url_http_scheme",
        ),
        CheckConstraint("length(title) BETWEEN 1 AND 255", name="title_length"),
        Index("ix_storefront_slides_render", "store_id", "is_active", "position"),
    )


class StorefrontSection(Base, UuidPk, Timestamped):
    __tablename__ = "storefront_sections"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    section_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # API-validated only (approved ruling; may embed product/category ids).
    config: Mapped[dict[str, Any] | None] = mapped_column(JsonVar, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="storefront_sections_store_fk",
        ),
        UniqueConstraint("store_id", "position", name="storefront_sections_position_unique"),
        CheckConstraint("position >= 1", name="position_min"),
        CheckConstraint(f"section_type IN {_SECTION_TYPES}", name="section_type_vocabulary"),
        CheckConstraint("length(title) BETWEEN 1 AND 255", name="title_length"),
        Index("ix_storefront_sections_render", "store_id", "is_active", "position"),
        Index("ix_storefront_sections_section_type", "section_type"),
    )


class StorefrontSettings(Base, UuidPk, Timestamped):
    __tablename__ = "storefront_settings"

    # store_id is UNIQUE => exactly one settings row per store (1:1).
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    theme: Mapped[dict[str, Any] | None] = mapped_column(JsonVar, nullable=True)
    social_links: Mapped[dict[str, Any] | None] = mapped_column(JsonVar, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="storefront_settings_store_fk",
        ),
        CheckConstraint(
            "contact_email IS NULL OR (length(contact_email) >= 3 AND contact_email LIKE '%@%.%')",
            name="contact_email_shape",
        ),
        CheckConstraint(
            "primary_color IS NULL OR (length(primary_color) = 7 AND primary_color LIKE '#%')",
            name="primary_color_shape",
        ),
    )


class StorefrontFooterLink(Base, UuidPk, Timestamped):
    __tablename__ = "storefront_footer_links"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="storefront_footer_links_store_fk",
        ),
        UniqueConstraint("store_id", "position", name="storefront_footer_links_position_unique"),
        CheckConstraint("position >= 1", name="position_min"),
        CheckConstraint("length(label) BETWEEN 1 AND 100", name="label_length"),
        CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'", name="url_http_scheme"
        ),
        Index("ix_storefront_footer_links_store_position", "store_id", "position"),
    )
