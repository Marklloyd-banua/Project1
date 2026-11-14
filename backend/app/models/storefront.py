"""Storefront models (migration 0003): slides, sections, settings, footer links.

JSONB columns (sections.config, settings.theme/social_links) are validated at
the API layer only — no database FKs can protect JSONB-embedded references
(approved ruling).
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
    # Optional same-store category link; migration 0003 defines the PostgreSQL
    # column-list `ON DELETE SET NULL (target_category_id)`.
    target_category_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
        # Hard cap of FOUR slides per store: position 1..4 + one per position.
        CheckConstraint("position BETWEEN 1 AND 4", name="position_range"),
        UniqueConstraint("store_id", "position", name="storefront_slides_position_unique"),
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
