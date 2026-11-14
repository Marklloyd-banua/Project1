"""inventory_adjustments model (migration 0002) — append-only ledger.

Append-only protection is enforced at the DATABASE level by privileges.sql:
the runtime role receives SELECT/INSERT only (UPDATE/DELETE revoked). No ORM
or API mutation route exists for this table either.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk


class InventoryAdjustment(Base, UuidPk, Timestamped):
    __tablename__ = "inventory_adjustments"

    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Ledger rows are never cascaded away: migration 0002 uses ON DELETE RESTRICT
    # so financial/inventory history survives (also gates store deletion).
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Denormalized snapshot at adjustment time (dashboard StockAdjustment).
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adjustment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    new_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
            name="inventory_adjustments_store_fk",
        ),
        ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="RESTRICT",
            name="inventory_adjustments_store_product_fk",
        ),
        # Inventory arithmetic integrity (authoritative invariants).
        CheckConstraint("previous_quantity >= 0", name="previous_quantity_nonnegative"),
        CheckConstraint("new_quantity >= 0", name="new_quantity_nonnegative"),
        CheckConstraint(
            "new_quantity = previous_quantity + adjustment_amount",
            name="adjustment_arithmetic",
        ),
        CheckConstraint("length(reason) >= 1", name="reason_required"),
        Index(
            "ix_inventory_adjustments_store_product_occurred",
            "store_id",
            "product_id",
            "occurred_at",
        ),
        Index("ix_inventory_adjustments_store_occurred", "store_id", "occurred_at"),
    )
