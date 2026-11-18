from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class StoreWorkspaceSummaryResponse(BaseModel):
    """Read-only workspace summary for an authorized store member."""

    store_id: UUID
    members_count: int = Field(ge=0)
    categories_count: int = Field(ge=0)
    products_count: int = Field(ge=0)
    active_products_count: int = Field(ge=0)
    customers_count: int = Field(ge=0)
    orders_count: int = Field(ge=0)
