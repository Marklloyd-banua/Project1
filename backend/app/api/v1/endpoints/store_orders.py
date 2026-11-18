from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.store import StoreMembership
from app.schemas.order import (
    OrderDetailResponse,
    OrderItemResponse,
    OrderListResponse,
    OrderStatusHistoryResponse,
    OrderSummaryResponse,
)
from app.schemas.pagination import PaginationParams, get_pagination_params

router = APIRouter(prefix="/stores", tags=["store-orders"])


@router.get("/{store_id}/orders", response_model=OrderListResponse)
def list_store_orders(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> OrderListResponse:
    """List orders for an authorized store (read-only).

    Store-scoped with DB-side count/order/pagination. Returns order snapshots
    and stored monetary values only (no recalculation, no customer/user joins).
    """
    base_where = Order.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(Order).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(Order)
        .where(base_where)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [OrderSummaryResponse.model_validate(row, from_attributes=True) for row in rows]
    return OrderListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{store_id}/orders/{order_id}", response_model=OrderDetailResponse)
def get_store_order(
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> OrderDetailResponse:
    """Retrieve an order with nested items and status history (read-only, store-scoped)."""
    # Detail lookup must match both order id and store_id; foreign-store ids return 404.
    order = db.execute(
        select(Order).where(Order.store_id == store_id, Order.id == order_id)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")

    # Nested records are always queried by store_id + order_id (no global fetch/filter).
    item_rows = db.execute(
        select(OrderItem)
        .where(OrderItem.store_id == store_id, OrderItem.order_id == order_id)
        .order_by(OrderItem.created_at.asc(), OrderItem.id.asc())
    ).scalars().all()
    history_rows = db.execute(
        select(OrderStatusHistory)
        .where(
            OrderStatusHistory.store_id == store_id,
            OrderStatusHistory.order_id == order_id,
        )
        .order_by(OrderStatusHistory.created_at.asc(), OrderStatusHistory.id.asc())
    ).scalars().all()

    return OrderDetailResponse(
        **OrderSummaryResponse.model_validate(order, from_attributes=True).model_dump(),
        cart_id=order.cart_id,
        ship_line1=order.ship_line1,
        ship_line2=order.ship_line2,
        ship_city=order.ship_city,
        ship_state=order.ship_state,
        ship_postal_code=order.ship_postal_code,
        ship_country=order.ship_country,
        notes=order.notes,
        items=[OrderItemResponse.model_validate(r, from_attributes=True) for r in item_rows],
        status_history=[
            OrderStatusHistoryResponse.model_validate(r, from_attributes=True)
            for r in history_rows
        ],
    )
