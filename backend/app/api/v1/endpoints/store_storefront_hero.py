from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member, require_store_owner_or_manager
from app.models.store import StoreMembership
from app.models.storefront import StorefrontSlide
from app.schemas.pagination import PaginationParams, get_pagination_params
from app.schemas.storefront_hero import (
    StorefrontHeroListResponse,
    StorefrontHeroMappingPatchRequest,
    StorefrontHeroMappingResponse,
    StorefrontHeroOrderUpdateRequest,
)
from app.services.storefront_hero import (
    FeaturedProductValidationError,
    ReorderValidationError,
    StorefrontHeroDomainError,
    assemble_storefront_hero_mapping_read,
    list_storefront_hero_mappings,
    reorder_mapped_categories,
    set_mapping_featured_product,
    sync_hero_mappings,
)

router = APIRouter(prefix="/stores", tags=["store-storefront-hero"])


@router.get(
    "/{store_id}/storefront/hero",
    response_model=StorefrontHeroListResponse,
)
def list_storefront_hero(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> StorefrontHeroListResponse:
    """List category-to-hero mappings for an authorized store (read-only, paginated)."""
    # All reads are store-scoped in the service layer; includes disabled/ineligible mappings.
    return list_storefront_hero_mappings(
        db,
        store_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.put(
    "/{store_id}/storefront/hero/order",
    response_model=StorefrontHeroListResponse,
)
def reorder_storefront_hero(
    store_id: uuid.UUID,
    payload: StorefrontHeroOrderUpdateRequest,
    membership: StoreMembership = Depends(require_store_owner_or_manager),
    db: Session = Depends(get_db),
) -> StorefrontHeroListResponse:
    """Apply complete owner/manager-controlled ordering for all mapped hero categories."""
    try:
        reorder_mapped_categories(db, store_id, payload.category_ids)
        db.commit()
    except ReorderValidationError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid hero ordering.",
        )

    # Return updated mappings using existing read/response assembly conventions.
    return list_storefront_hero_mappings(db, store_id, page=1, page_size=20)


@router.patch(
    "/{store_id}/storefront/hero/categories/{category_id}",
    response_model=StorefrontHeroMappingResponse,
)
def patch_storefront_hero_mapping(
    store_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: StorefrontHeroMappingPatchRequest,
    membership: StoreMembership = Depends(require_store_owner_or_manager),
    db: Session = Depends(get_db),
) -> StorefrontHeroMappingResponse:
    """Partially update a mapped hero category (enablement and/or featured product selection)."""
    updates = payload.model_dump(exclude_unset=True)

    # Store-scoped mapping lookup (authorized store only; missing => 404, no foreign-store disclosure).
    slide = db.execute(
        select(StorefrontSlide).where(
            StorefrontSlide.store_id == store_id,
            StorefrontSlide.category_id == category_id,
        )
    ).scalar_one_or_none()
    if slide is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")

    try:
        if "featured_product_id" in updates:
            # Reuse B1 service for manual featured-product set/clear validation and update.
            admin_is_enabled = updates.get("admin_is_enabled")
            slide = set_mapping_featured_product(
                db,
                store_id,
                category_id,
                updates["featured_product_id"],
                admin_is_enabled=admin_is_enabled,
            )
        elif "admin_is_enabled" in updates:
            # Enablement-only update: preserve stored featured selection without revalidation/clearing.
            slide.admin_is_enabled = bool(updates["admin_is_enabled"])
            db.flush()
        # No-op when no fields provided: return current assembled mapping.
        db.commit()
    except FeaturedProductValidationError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid featured product selection.",
        )
    except StorefrontHeroDomainError as exc:
        db.rollback()
        # Reuse existing B1 domain signal for missing mapping; do not translate unexpected errors broadly.
        if str(exc) == "Category mapping not found for store.":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")
        raise

    db.refresh(slide)
    return assemble_storefront_hero_mapping_read(db, slide)


@router.post(
    "/{store_id}/storefront/hero/sync",
    response_model=StorefrontHeroListResponse,
)
def sync_storefront_hero(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_owner_or_manager),
    db: Session = Depends(get_db),
) -> StorefrontHeroListResponse:
    """Create missing hero mappings for all store categories (idempotent, preserves intent)."""
    sync_hero_mappings(db, store_id)
    db.commit()
    return list_storefront_hero_mappings(db, store_id, page=1, page_size=20)
