from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.category import Category
from app.models.customer import Customer
from app.models.order import Order
from app.models.product import Product
from app.models.store import StoreMembership
from app.schemas.store_workspace import StoreWorkspaceSummaryResponse

router = APIRouter(prefix="/stores", tags=["store-workspace"])


@router.get("/{store_id}/workspace/summary", response_model=StoreWorkspaceSummaryResponse)
def get_store_workspace_summary(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> StoreWorkspaceSummaryResponse:
    """Return store-scoped workspace aggregate counts for an authorized store member.

    Authorization and 401/403 semantics are enforced by existing dependencies:
    - unauthenticated/inactive => 401 (generic)
    - non-member, platform admin without membership, unknown role => 403 (generic)
    Viewers may read. Every aggregate is scoped by the authorized path store_id.
    """

    # Use scalar aggregate COUNT queries scoped to store_id (no table loads, no N+1).
    members_count = db.execute(
        select(func.count()).select_from(StoreMembership).where(StoreMembership.store_id == store_id)
    ).scalar_one()
    categories_count = db.execute(
        select(func.count()).select_from(Category).where(Category.store_id == store_id)
    ).scalar_one()
    products_count = db.execute(
        select(func.count()).select_from(Product).where(Product.store_id == store_id)
    ).scalar_one()
    active_products_count = db.execute(
        select(func.count())
        .select_from(Product)
        .where(Product.store_id == store_id, Product.status == "Active")
    ).scalar_one()
    customers_count = db.execute(
        select(func.count()).select_from(Customer).where(Customer.store_id == store_id)
    ).scalar_one()
    orders_count = db.execute(
        select(func.count()).select_from(Order).where(Order.store_id == store_id)
    ).scalar_one()

    return StoreWorkspaceSummaryResponse(
        store_id=store_id,
        members_count=int(members_count),
        categories_count=int(categories_count),
        products_count=int(products_count),
        active_products_count=int(active_products_count),
        customers_count=int(customers_count),
        orders_count=int(orders_count),
    )
