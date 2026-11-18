from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StoreMembershipStaffSummary(BaseModel):
    id: UUID
    email: str
    full_name: str


class StoreMembershipResponse(BaseModel):
    id: UUID
    store_id: UUID
    staff_user_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime
    staff: StoreMembershipStaffSummary


class StoreMembershipListResponse(BaseModel):
    items: list[StoreMembershipResponse]
