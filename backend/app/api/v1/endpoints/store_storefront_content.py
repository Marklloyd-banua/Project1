from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.store import StoreMembership
from app.models.storefront import StorefrontFooterLink, StorefrontSection, StorefrontSlide
from app.schemas.pagination import PaginationParams, get_pagination_params
from app.schemas.storefront_content import (
    StorefrontFooterLinkListResponse,
    StorefrontFooterLinkResponse,
    StorefrontSectionListResponse,
    StorefrontSectionResponse,
    StorefrontSlideListResponse,
    StorefrontSlideResponse,
)

router = APIRouter(prefix="/stores", tags=["store-storefront-content"])


@router.get(
    "/{store_id}/storefront/slides",
    response_model=StorefrontSlideListResponse,
)
def list_storefront_slides(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> StorefrontSlideListResponse:
    """List storefront slides for an authorized store (read-only)."""
    base_where = StorefrontSlide.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(StorefrontSlide).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(StorefrontSlide)
        .where(base_where)
        .order_by(StorefrontSlide.position.asc(), StorefrontSlide.id.asc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [StorefrontSlideResponse.model_validate(row, from_attributes=True) for row in rows]
    return StorefrontSlideListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{store_id}/storefront/sections",
    response_model=StorefrontSectionListResponse,
)
def list_storefront_sections(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> StorefrontSectionListResponse:
    """List storefront sections for an authorized store (read-only).

    Section config is returned as stored JSON value or null without transformation.
    """
    base_where = StorefrontSection.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(StorefrontSection).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(StorefrontSection)
        .where(base_where)
        .order_by(StorefrontSection.position.asc(), StorefrontSection.id.asc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [StorefrontSectionResponse.model_validate(row, from_attributes=True) for row in rows]
    return StorefrontSectionListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{store_id}/storefront/footer-links",
    response_model=StorefrontFooterLinkListResponse,
)
def list_storefront_footer_links(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> StorefrontFooterLinkListResponse:
    """List storefront footer links for an authorized store (read-only)."""
    base_where = StorefrontFooterLink.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(StorefrontFooterLink).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(StorefrontFooterLink)
        .where(base_where)
        .order_by(StorefrontFooterLink.position.asc(), StorefrontFooterLink.id.asc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [StorefrontFooterLinkResponse.model_validate(row, from_attributes=True) for row in rows]
    return StorefrontFooterLinkListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )
