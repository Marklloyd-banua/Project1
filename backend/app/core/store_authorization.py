"""Store-membership authorization primitives for Northstar backend (B1.4B).

Authentication and active-user checks (401) are handled by
``get_current_active_staff_user``. This module provides store-membership
authorization (403) based on the current database-loaded membership record.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_staff_user
from app.core.db import get_db
from app.models.staff_user import StaffUser
from app.models.store import StoreMembership

_CANONICAL_STORE_ROLES = {"owner", "manager", "viewer"}


def has_store_role(membership: StoreMembership, *allowed_roles: str) -> bool:
    """Return True when the membership's database role is allowed."""
    return membership.role in allowed_roles


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden.",
    )


def get_store_membership(
    store_id: uuid.UUID,
    current_user: StaffUser = Depends(get_current_active_staff_user),
    db: Session = Depends(get_db),
) -> StoreMembership:
    """Load and return the current user's membership for the requested store.

    The membership is resolved by both the requested store UUID and the
    authenticated user's database UUID. Missing membership, nonexistent store,
    or unknown membership role results in a generic 403 response.
    """
    membership = db.execute(
        select(StoreMembership).where(
            StoreMembership.store_id == store_id,
            StoreMembership.staff_user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if membership is None:
        raise _forbidden()

    if membership.role not in _CANONICAL_STORE_ROLES:
        raise _forbidden()

    return membership


def _require_store_roles(*allowed_roles: str) -> Callable[..., StoreMembership]:
    if not allowed_roles:
        raise ValueError("At least one allowed store role must be provided.")
    if any(role not in _CANONICAL_STORE_ROLES for role in allowed_roles):
        raise ValueError(
            "Allowed store roles must be canonical: owner, manager, viewer."
        )

    def _dependency(
        membership: StoreMembership = Depends(get_store_membership),
    ) -> StoreMembership:
        if not has_store_role(membership, *allowed_roles):
            raise _forbidden()
        return membership

    return _dependency


require_store_member = _require_store_roles("owner", "manager", "viewer")
require_store_owner_or_manager = _require_store_roles("owner", "manager")
require_store_owner = _require_store_roles("owner")
