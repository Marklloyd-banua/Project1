from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.schemas.pagination import PaginatedResponse


class StorefrontSlideResponse(BaseModel):
    id: UUID
    store_id: UUID
    title: str
    subtitle: str | None
    image_url: str
    cta_url: str | None
    cta_label: str | None
    position: int
    target_category_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StorefrontSectionResponse(BaseModel):
    id: UUID
    store_id: UUID
    section_type: str
    title: str
    subtitle: str | None
    position: int
    is_active: bool
    config: Any | None
    created_at: datetime
    updated_at: datetime


class StorefrontFooterLinkResponse(BaseModel):
    id: UUID
    store_id: UUID
    label: str
    url: str
    position: int
    created_at: datetime
    updated_at: datetime


class StorefrontSlideListResponse(PaginatedResponse[StorefrontSlideResponse]):
    """Paginated storefront slides list envelope for B1.5B."""


class StorefrontSectionListResponse(PaginatedResponse[StorefrontSectionResponse]):
    """Paginated storefront sections list envelope for B1.5B."""


class StorefrontFooterLinkListResponse(PaginatedResponse[StorefrontFooterLinkResponse]):
    """Paginated storefront footer links list envelope for B1.5B."""
