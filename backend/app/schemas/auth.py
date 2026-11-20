from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def normalize_email(email: str) -> str:
    return email.strip().lower()


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not normalized or "@" not in normalized:
            raise ValueError("Invalid email")
        return normalized


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    global_role: str
    status: str


class AuthenticatedStoreMembershipItem(BaseModel):
    store_id: UUID
    store_name: str
    store_status: str
    membership_role: Literal["owner", "manager", "viewer"]


class AuthenticatedStoreMembershipListResponse(BaseModel):
    items: list[AuthenticatedStoreMembershipItem]
