from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_serializer

from app.schemas.pagination import PaginatedResponse


class OrderItemResponse(BaseModel):
    id: UUID
    store_id: UUID
    order_id: UUID
    product_id: UUID | None
    product_name: str
    product_sku: str | None
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    created_at: datetime
    updated_at: datetime

    @field_serializer("unit_price", "line_total")
    def serialize_money(self, value: Decimal) -> str:
        # Monetary values must serialize as JSON strings to preserve precision (never float).
        return format(value, "f")


class OrderStatusHistoryResponse(BaseModel):
    id: UUID
    store_id: UUID
    order_id: UUID
    previous_status: str
    new_status: str
    reason: str
    actor_id: UUID | None
    actor_name: str | None
    actor_email: str | None
    created_at: datetime
    updated_at: datetime


class OrderSummaryResponse(BaseModel):
    id: UUID
    store_id: UUID
    order_number: str
    customer_id: UUID | None
    customer_name: str
    customer_email: str
    customer_phone: str | None
    payment_status: str
    fulfillment_status: str
    subtotal: Decimal
    shipping_cost: Decimal
    discount: Decimal
    total: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("subtotal", "shipping_cost", "discount", "total")
    def serialize_money(self, value: Decimal) -> str:
        # Monetary values must serialize as JSON strings to preserve precision (never float).
        return format(value, "f")


class OrderDetailResponse(OrderSummaryResponse):
    cart_id: UUID | None
    ship_line1: str
    ship_line2: str | None
    ship_city: str
    ship_state: str | None
    ship_postal_code: str
    ship_country: str
    notes: str | None
    items: list[OrderItemResponse]
    status_history: list[OrderStatusHistoryResponse]


class OrderListResponse(PaginatedResponse[OrderSummaryResponse]):
    """Paginated order list envelope for B1.5B."""
