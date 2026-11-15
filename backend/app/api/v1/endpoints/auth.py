from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import InvalidTokenError, create_access_token, decode_access_token, verify_password
from app.models.staff_user import StaffUser
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])
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


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = normalize_email(payload.email)
    stmt = select(StaffUser).where(StaffUser.email == email)
    user = db.execute(stmt).scalar_one_or_none()

    if user is None or user.password_hash is None:
        raise _unauthorized()
    if not verify_password(payload.password, user.password_hash):
        raise _unauthorized()
    if user.status != "Active":
        raise _unauthorized()

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
def me(current_user: StaffUser = Depends(get_current_active_staff_user)) -> MeResponse:
    return MeResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        global_role=current_user.global_role,
        status=current_user.status,
    )
