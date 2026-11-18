from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.store_authorization import require_store_member
from app.models.staff_user import StaffUser
from app.models.store import StoreMembership
from app.schemas.store_membership import (
    StoreMembershipListResponse,
    StoreMembershipResponse,
    StoreMembershipStaffSummary,
)

router = APIRouter(prefix="/stores", tags=["store-memberships"])


@router.get("/{store_id}/members", response_model=StoreMembershipListResponse)
def list_store_members(
    store_id: uuid.UUID,
    membership: StoreMembership = Depends(require_store_member),
    db: Session = Depends(get_db),
) -> StoreMembershipListResponse:
    rows = db.execute(
        select(StoreMembership, StaffUser)
        .join(StaffUser, StaffUser.id == StoreMembership.staff_user_id)
        .where(StoreMembership.store_id == store_id)
        .order_by(StoreMembership.created_at.asc(), StoreMembership.id.asc())
    ).all()

    items: list[StoreMembershipResponse] = []
    for m, staff in rows:
        items.append(
            StoreMembershipResponse(
                id=m.id,
                store_id=m.store_id,
                staff_user_id=m.staff_user_id,
                role=m.role,
                created_at=m.created_at,
                updated_at=m.updated_at,
                staff=StoreMembershipStaffSummary(
                    id=staff.id,
                    email=staff.email,
                    full_name=staff.full_name,
                ),
            )
        )

    return StoreMembershipListResponse(items=items)
