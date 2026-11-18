from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.product import Product, ProductImage
from app.models.store import StoreMembership
from app.schemas.pagination import PaginationParams, get_pagination_params
from app.schemas.product import (
    ProductDetailResponse,
    ProductImageResponse,
    ProductListResponse,
    ProductSummaryResponse,
)

router = APIRouter(prefix="/stores", tags=["store-products"])


@router.get("/{store_id}/products", response_model=ProductListResponse)
def list_store_products(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    """List products for an authorized store (deterministic, paginated).

    All queries are scoped by store_id and executed with DB-side count/order/pagination.
    """
    base_where = Product.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(Product).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(Product)
        .where(base_where)
        .order_by(Product.created_at.desc(), Product.id.desc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [ProductSummaryResponse.model_validate(row, from_attributes=True) for row in rows]
    return ProductListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{store_id}/products/{product_id}", response_model=ProductDetailResponse)
def get_store_product(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> ProductDetailResponse:
    """Retrieve a product and its ordered images within the authorized store scope."""
    # Detail lookup must match both resource id and store_id; foreign-store ids return 404.
    product = db.execute(
        select(Product).where(
            Product.store_id == store_id,
            Product.id == product_id,
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")

    # Images must be scoped to both store_id and product_id (no global load/filter).
    image_rows = db.execute(
        select(ProductImage)
        .where(
            ProductImage.store_id == store_id,
            ProductImage.product_id == product_id,
        )
        .order_by(ProductImage.position.asc(), ProductImage.id.asc())
    ).scalars().all()

    product_data = ProductSummaryResponse.model_validate(product, from_attributes=True).model_dump()
    product_data["images"] = [
        ProductImageResponse.model_validate(img, from_attributes=True).model_dump()
        for img in image_rows
    ]
    return ProductDetailResponse.model_validate(product_data)
