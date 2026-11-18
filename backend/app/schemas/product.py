from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_serializer

from app.schemas.pagination import PaginatedResponse


class ProductImageResponse(BaseModel):
    id: UUID
    product_id: UUID
    store_id: UUID
    url: str
    alt: str | None
    position: int
    created_at: datetime
    updated_at: datetime


class ProductSummaryResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    slug: str
    description: str
    image: str
    category_id: UUID | None
    category: str | None
    price: Decimal
    stock_quantity: int
    low_stock_threshold: int
    sku: str | None
    status: str
    inventory_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("price")
    def serialize_price(self, value: Decimal) -> str:
        # Monetary values must serialize as JSON strings to preserve precision (never float).
        return format(value, "f")


class ProductDetailResponse(ProductSummaryResponse):
    images: list[ProductImageResponse]


class ProductListResponse(PaginatedResponse[ProductSummaryResponse]):
    """Paginated product list envelope for B1.5B."""
