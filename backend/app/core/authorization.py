"""Global-role authorization primitives for Northstar backend (B1.4A).

Authentication (401: missing/invalid/inactive credentials or user state) is handled
by the existing ``get_current_active_staff_user`` dependency. This module provides
authorization (403) checks for authenticated, active staff users based on the
current database-loaded ``global_role``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_active_staff_user
from app.models.staff_user import StaffUser


def has_global_role(user: StaffUser, *allowed_roles: str) -> bool:
    """Return True when the current database-loaded user's global role is allowed."""
    return user.global_role in allowed_roles


_CANONICAL_GLOBAL_ROLES = {"administrator", "manager", "viewer"}


def require_global_roles(*allowed_roles: str) -> Callable[..., StaffUser]:
    """Create a FastAPI dependency requiring one of the allowed global roles.

    The dependency reuses ``get_current_active_staff_user`` so authentication and
    active-user checks (HTTP 401) remain unchanged. Authenticated active users whose
    ``global_role`` is not allowed receive HTTP 403 with the standard error envelope.
    """
    if not allowed_roles:
        raise ValueError("At least one allowed global role must be provided.")
    if any(role not in _CANONICAL_GLOBAL_ROLES for role in allowed_roles):
        raise ValueError("Allowed global roles must be canonical: administrator, manager, viewer.")

    def _require_global_roles(
        current_user: StaffUser = Depends(get_current_active_staff_user),
    ) -> StaffUser:
        if not has_global_role(current_user, *allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden.",
            )
        return current_user

    return _require_global_roles


require_platform_admin = require_global_roles("administrator")
