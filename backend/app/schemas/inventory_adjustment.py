from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.pagination import PaginatedResponse


class InventoryAdjustmentResponse(BaseModel):
    id: UUID
    store_id: UUID
    product_id: UUID
    product_name: str | None
    sku: str | None
    adjustment_amount: int
    previous_quantity: int
    new_quantity: int
    reason: str
    actor_id: UUID | None
    actor_name: str | None
    actor_email: str | None
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime


class InventoryAdjustmentListResponse(PaginatedResponse[InventoryAdjustmentResponse]):
    """Paginated inventory adjustment list envelope for B1.5B."""
