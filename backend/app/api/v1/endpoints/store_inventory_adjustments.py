from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.store import StoreMembership
from app.schemas.inventory_adjustment import (
    InventoryAdjustmentListResponse,
    InventoryAdjustmentResponse,
)
from app.schemas.pagination import PaginationParams, get_pagination_params

router = APIRouter(prefix="/stores", tags=["store-inventory-adjustments"])


@router.get(
    "/{store_id}/inventory-adjustments",
    response_model=InventoryAdjustmentListResponse,
)
def list_store_inventory_adjustments(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> InventoryAdjustmentListResponse:
    """List inventory adjustments for an authorized store (read-only, append-only ledger).

    Every query is scoped by store_id with DB-side count/order/pagination.
    Snapshot fields are returned as stored; no recalculation or side effects.
    """
    base_where = InventoryAdjustment.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(InventoryAdjustment).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(InventoryAdjustment)
        .where(base_where)
        .order_by(
            InventoryAdjustment.occurred_at.desc(),
            InventoryAdjustment.created_at.desc(),
            InventoryAdjustment.id.desc(),
        )
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [
        InventoryAdjustmentResponse.model_validate(row, from_attributes=True) for row in rows
    ]
    return InventoryAdjustmentListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{store_id}/inventory-adjustments/{adjustment_id}",
    response_model=InventoryAdjustmentResponse,
)
def get_store_inventory_adjustment(
    store_id: uuid.UUID,
    adjustment_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> InventoryAdjustmentResponse:
    """Retrieve an inventory adjustment within the authorized store scope."""
    # Detail lookup must match both adjustment id and store_id; foreign-store ids return 404.
    adjustment = db.execute(
        select(InventoryAdjustment).where(
            InventoryAdjustment.store_id == store_id,
            InventoryAdjustment.id == adjustment_id,
        )
    ).scalar_one_or_none()
    if adjustment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")
    return InventoryAdjustmentResponse.model_validate(adjustment, from_attributes=True)
