from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.pagination import PaginatedResponse


class CustomerAddressResponse(BaseModel):
    id: UUID
    store_id: UUID
    customer_id: UUID
    label: str | None
    line1: str
    line2: str | None
    city: str
    state: str | None
    postal_code: str
    country: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class CustomerSummaryResponse(BaseModel):
    id: UUID
    store_id: UUID
    email: str
    full_name: str
    phone: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CustomerDetailResponse(CustomerSummaryResponse):
    addresses: list[CustomerAddressResponse]


class CustomerListResponse(PaginatedResponse[CustomerSummaryResponse]):
    """Paginated customer list envelope for B1.5B."""
