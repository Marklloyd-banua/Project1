"""B2 (foundation): request/response contracts for storefront hero admin APIs.

This module defines isolated Pydantic schemas for the proposed B2 category-to-hero
admin endpoints. Endpoint handlers/routers/service orchestration are implemented in
later approved batches; this batch establishes API contract and schema foundation only.

Contract notes (approved B2 planning/batch scope):
- GET  /stores/{store_id}/storefront/hero
  - Paginated list envelope: {"items", "total", "page", "page_size"} (existing conventions).
  - Returns all category-to-hero mappings for the store, including currently ineligible
    mappings, with stored admin intent, stored manual selection, eligibility visibility,
    and effective featured-product resolution/fallback visibility. Stored invalid manual
    selections must remain preserved (not erased) when surfaced by read/behavior layers.
- PUT  /stores/{store_id}/storefront/hero/order
  - Body accepts "category_ids" as the intended complete ordering of mapped categories.
  - Must include every currently mapped category exactly once (including disabled and
    currently ineligible mappings). Duplicates/missing/unknown/foreign-store IDs are invalid.
- PATCH /stores/{store_id}/storefront/hero/categories/{category_id}
  - Omitted fields remain unchanged (exclude_unset semantics).
  - "featured_product_id": null clears the manual featured product selection.
  - Category without an existing mapping => 404 (sync creates missing mappings).
  - Invalid selections => 422 (consistent with existing API conventions).
- POST /stores/{store_id}/storefront/hero/sync
  - Creates mappings for all store categories, preserving existing mapping IDs/order intent,
    admin enablement, featured-product selections, and legacy/unmapped slide rows.
  - Idempotent and duplicate-free by (store_id, category_id).

Schemas intentionally avoid exposing private store/product data beyond store-member-visible
hero/admin context fields required by the contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PaginatedResponse


FeaturedResolutionSource = Literal["manual", "fallback", "none"]


class StorefrontHeroFeaturedProductResponse(BaseModel):
    """Effective featured product surfaced for a hero mapping (safe/admin-visible fields)."""

    id: UUID
    store_id: UUID
    category_id: UUID | None
    name: str
    slug: str
    image: str | None
    status: str


class StorefrontHeroEligibilityResponse(BaseModel):
    """Eligibility signals for public hero visibility of a mapped category."""

    category_active: bool
    has_eligible_active_product: bool
    is_publicly_eligible: bool


class StorefrontHeroMappingResponse(BaseModel):
    """Category-to-hero mapping with stored intent and effective resolution visibility.

    Includes legacy storefront slide fields for compatibility/traceability (not repurposed).
    """

    # Mapping identity and scope
    id: UUID
    store_id: UUID
    category_id: UUID

    # Owner-controlled ordering and admin/public state
    position: int = Field(ge=1)
    admin_is_enabled: bool
    is_active: bool

    # Stored manual selection (preserved even when invalid/ineligible; null means none/cleared)
    featured_product_id: UUID | None

    # Eligibility and effective resolution (derived by service/read layer; no mutation on read)
    eligibility: StorefrontHeroEligibilityResponse
    manual_featured_product_valid: bool
    effective_featured_product: StorefrontHeroFeaturedProductResponse | None
    featured_resolution_source: FeaturedResolutionSource

    # Legacy storefront slide fields (preserved for B1.5B/B1.6 compatibility; read-only context)
    title: str
    subtitle: str | None
    image_url: str
    cta_url: str | None
    cta_label: str | None
    target_category_id: UUID | None

    created_at: datetime
    updated_at: datetime


class StorefrontHeroListResponse(PaginatedResponse[StorefrontHeroMappingResponse]):
    """Paginated hero mappings list envelope for GET /stores/{store_id}/storefront/hero."""


class StorefrontHeroOrderUpdateRequest(BaseModel):
    """Complete mapped-category ordering for PUT /stores/{store_id}/storefront/hero/order.

    "category_ids" must contain every currently mapped category for the store exactly once,
    including disabled and currently ineligible mappings. Duplicates, missing mapped
    categories, unknown mappings, or foreign-store IDs are invalid (422).
    """

    model_config = ConfigDict(extra="forbid")

    category_ids: list[UUID]


class StorefrontHeroMappingPatchRequest(BaseModel):
    """Partial update for PATCH /stores/{store_id}/storefront/hero/categories/{category_id}.

    Omitted fields remain unchanged (PATCH handlers must use model_dump(exclude_unset=True)).
    Explicit null for "featured_product_id" clears the stored manual selection.
    """

    model_config = ConfigDict(extra="forbid")

    # Omitted => unchanged (excluded when exclude_unset=True); when provided, must be true/false.
    admin_is_enabled: bool = False
    # Omitted => unchanged; explicit null => clear manual selection; UUID => set/replace selection.
    featured_product_id: UUID | None = None


# NOTE: POST /stores/{store_id}/storefront/hero/sync has no request body.
# Missing mapping for PATCH target => 404. Invalid selection/order => 422.
