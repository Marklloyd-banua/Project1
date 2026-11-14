"""stores, store_memberships, store_order_counters models (migration 0001)."""

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

_PLANS = "('Free','Starter','Professional','Enterprise')"


class Store(Base, UuidPk, Timestamped):
    __tablename__ = "stores"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Owner DISPLAY NAME (mirrors dashboard Store.owner; the owning membership
    # is enforced separately by store_memberships).
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    # Hostname-only identity, globally unique. The regex format CHECK is
    # PostgreSQL-only and lives in migration 0001 (authoritative).
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Free", server_default="Free"
    )
    mrr: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default=text("0")
    )
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    banner_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    business_address: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Free-form on purpose (dashboard EntityStatus union is shared; no CHECK).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Active", server_default="Active"
    )

    __table_args__ = (
        CheckConstraint("domain = lower(domain)", name="domain_lowercase"),
        CheckConstraint(f"plan IN {_PLANS}", name="plan_vocabulary"),
        CheckConstraint("mrr >= 0", name="mrr_nonnegative"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_alpha3",
        ),
    )


class StoreMembership(Base, UuidPk, Timestamped):
    __tablename__ = "store_memberships"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    staff_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer", server_default="viewer"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="store_memberships_store_fk",
        ),
        ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            ondelete="CASCADE",
            name="store_memberships_staff_user_fk",
        ),
        UniqueConstraint("store_id", "staff_user_id", name="membership_unique"),
        CheckConstraint(
            "role IN ('owner','manager','viewer')", name="role_vocabulary"
        ),
        # One owner per store (partial unique index; portable via both dialects).
        Index(
            "uq_one_owner_per_store",
            "store_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
            sqlite_where=text("role = 'owner'"),
        ),
        Index("ix_store_memberships_staff_user_id", "staff_user_id"),
    )


class StoreOrderCounter(Base):
    """Per-store gap-free order-number counter (1:1 with stores).

    Initialized to 0 by the migration's ``trg_stores_init_counter`` trigger on
    PostgreSQL; rows are created explicitly elsewhere. Allocation uses row
    locking inside the checkout transaction (Phase 3).
    """

    __tablename__ = "store_order_counters"

    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    last_order_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="store_order_counters_store_fk",
        ),
        CheckConstraint(
            "last_order_number >= 0", name="last_order_number_nonnegative"
        ),
    )
