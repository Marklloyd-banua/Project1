from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.customer import Customer, CustomerAddress
from app.models.store import StoreMembership
from app.schemas.customer import (
    CustomerAddressResponse,
    CustomerDetailResponse,
    CustomerListResponse,
    CustomerSummaryResponse,
)
from app.schemas.pagination import PaginationParams, get_pagination_params

router = APIRouter(prefix="/stores", tags=["store-customers"])


@router.get("/{store_id}/customers", response_model=CustomerListResponse)
def list_store_customers(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: Session = Depends(get_db),
) -> CustomerListResponse:
    """List customers for an authorized store (read-only).

    Store-scoped with DB-side count/order/pagination. Returns stored customer
    snapshot/status fields only (no joins, no fabricated data).
    """
    base_where = Customer.store_id == store_id

    total = db.execute(
        select(func.count()).select_from(Customer).where(base_where)
    ).scalar_one()

    offset = (pagination.page - 1) * pagination.page_size
    rows = db.execute(
        select(Customer)
        .where(base_where)
        .order_by(Customer.created_at.desc(), Customer.id.desc())
        .offset(offset)
        .limit(pagination.page_size)
    ).scalars().all()

    items = [CustomerSummaryResponse.model_validate(row, from_attributes=True) for row in rows]
    return CustomerListResponse(
        items=items,
        total=int(total),
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{store_id}/customers/{customer_id}", response_model=CustomerDetailResponse)
def get_store_customer(
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> CustomerDetailResponse:
    """Retrieve a customer and nested addresses (read-only, store-scoped)."""
    # Detail lookup must match both customer id and store_id; foreign-store ids return 404.
    customer = db.execute(
        select(Customer).where(Customer.store_id == store_id, Customer.id == customer_id)
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found.")

    # Nested addresses are always queried by store_id + customer_id (no global fetch/filter).
    address_rows = db.execute(
        select(CustomerAddress)
        .where(
            CustomerAddress.store_id == store_id,
            CustomerAddress.customer_id == customer_id,
        )
        .order_by(
            CustomerAddress.is_default.desc(),
            CustomerAddress.created_at.asc(),
            CustomerAddress.id.asc(),
        )
    ).scalars().all()

    return CustomerDetailResponse(
        **CustomerSummaryResponse.model_validate(customer, from_attributes=True).model_dump(),
        addresses=[
            CustomerAddressResponse.model_validate(r, from_attributes=True)
            for r in address_rows
        ],
    )
