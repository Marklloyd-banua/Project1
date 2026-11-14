"""customers, customer_addresses models (migration 0004)."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Boolean,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk


class Customer(Base, UuidPk, Timestamped):
    __tablename__ = "customers"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Soft delete via status — customers are never hard-deleted while carts or
    # orders reference them (RESTRICT on those FKs).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Active", server_default="Active"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="customers_store_fk"
        ),
        UniqueConstraint("store_id", "email", name="customers_store_email_unique"),
        # Composite-FK target for carts/orders/customer_addresses.
        UniqueConstraint("store_id", "id", name="customers_store_id_unique"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("status IN ('Active','Suspended')", name="status_vocabulary"),
        Index("ix_customers_store_status", "store_id", "status"),
    )


class CustomerAddress(Base, UuidPk, Timestamped):
    __tablename__ = "customer_addresses"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    line1: Mapped[str] = mapped_column(String(255), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="customer_addresses_store_fk",
        ),
        ForeignKeyConstraint(
            ["store_id", "customer_id"],
            ["customers.store_id", "customers.id"],
            ondelete="CASCADE",
            name="customer_addresses_store_customer_fk",
        ),
        # One default address per customer (partial unique index).
        Index(
            "uq_default_address_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        CheckConstraint("length(line1) BETWEEN 1 AND 255", name="line1_length"),
        CheckConstraint("length(city) BETWEEN 1 AND 255", name="city_length"),
        CheckConstraint("length(postal_code) BETWEEN 1 AND 20", name="postal_code_length"),
        CheckConstraint("length(country) BETWEEN 2 AND 3", name="country_length"),
    )
