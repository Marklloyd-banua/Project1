from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import InvalidTokenError, decode_access_token
from app.models.staff_user import StaffUser

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_active_staff_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> StaffUser:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
    except InvalidTokenError:
        raise _unauthorized()

    if not isinstance(subject, str) or not subject.strip():
        raise _unauthorized()

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise _unauthorized()

    user = db.get(StaffUser, user_id)
    if user is None or user.status != "Active":
        raise _unauthorized()
    return user
