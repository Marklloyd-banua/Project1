"""categories model (migration 0002)."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk


class Category(Base, UuidPk, Timestamped):
    __tablename__ = "categories"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    image: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Active", server_default="Active"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="categories_store_fk"
        ),
        # Slug unique per store; duplicate NAMES are allowed on purpose.
        UniqueConstraint("store_id", "slug", name="categories_store_slug_unique"),
        # Composite-FK target for products.category_id and slides.target_category_id.
        UniqueConstraint("store_id", "id", name="categories_store_id_unique"),
        CheckConstraint("length(name) BETWEEN 1 AND 255", name="name_length"),
        CheckConstraint("status IN ('Active','Draft')", name="status_vocabulary"),
        # Dashboard slug regex is PostgreSQL-only (`~`) and lives in migration
        # 0002; the portable lowercase invariant is carried here.
        CheckConstraint("slug = lower(slug)", name="slug_lowercase"),
        Index("ix_categories_store_status", "store_id", "status"),
    )
