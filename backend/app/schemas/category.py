from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.pagination import PaginatedResponse


class CategoryResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    slug: str
    description: str | None
    image: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CategoryListResponse(PaginatedResponse[CategoryResponse]):
    """Paginated category list envelope for B1.5B."""
