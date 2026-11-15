from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import _unauthorized, get_current_active_staff_user
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.staff_user import StaffUser
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])


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
