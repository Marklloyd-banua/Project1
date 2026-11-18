from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.category import Category
from app.models.store import StoreMembership
from app.schemas.category import CategoryListResponse, CategoryResponse
from app.schemas.pagination import PaginationParams, get_pagination_params

router = APIRouter(prefix="/stores", tags=["store-categories"])


@router.get("/{store_id}/categories", response_model=CategoryListResponse)
def list_store_categories(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> CategoryListResponse:
    """List categories for an authorized store (deterministic, paginated).

    Every query is scoped by store_id; no global fetch/filter in Python.
    """
    base_where = Category.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(Category).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(Category)
        .where(base_where)
        .order_by(Category.name.asc(), Category.id.asc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [CategoryResponse.model_validate(row, from_attributes=True) for row in rows]
    return CategoryListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{store_id}/categories/{category_id}", response_model=CategoryResponse)
def get_store_category(
    store_id: uuid.UUID,
    category_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> CategoryResponse:
    """Retrieve a category by id within the authorized store scope."""
    # Detail lookup must match both resource id and store_id; foreign-store ids return 404.
    category = db.execute(
        select(Category).where(
            Category.store_id == store_id,
            Category.id == category_id,
        )
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")
    return CategoryResponse.model_validate(category, from_attributes=True)
