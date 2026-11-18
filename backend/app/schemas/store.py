from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator


class StoreProfileResponse(BaseModel):
    id: UUID
    name: str
    owner: str
    domain: str
    plan: str
    mrr: Decimal
    currency: str
    status: str
    description: str | None
    logo_image_url: str | None
    banner_image_url: str | None
    contact_email: str | None
    phone_number: str | None
    business_address: str | None
    timezone: str | None
    date_format: str | None
    created_at: datetime
    updated_at: datetime


class StoreProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    logo_image_url: str | None = None
    banner_image_url: str | None = None
    contact_email: str | None = None
    phone_number: str | None = None
    business_address: str | None = None
    timezone: str | None = None
    date_format: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must not be null")
        name = value.strip()
        if not name:
            raise ValueError("name must not be empty")
        if len(name) > 255:
            raise ValueError("name must be at most 255 characters")
        return name

    @field_validator("logo_image_url", "banner_image_url")
    @classmethod
    def validate_image_urls(cls, value: str | None) -> str | None:
        if value is None:
            return value
        url = value.strip()
        if len(url) > 2048:
            raise ValueError("URL must be at most 2048 characters")
        return url

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        email = value.strip()
        if len(email) > 255:
            raise ValueError("contact_email must be at most 255 characters")
        return email

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return value
        phone = value.strip()
        if len(phone) > 50:
            raise ValueError("phone_number must be at most 50 characters")
        return phone

    @field_validator("business_address", "description")
    @classmethod
    def validate_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        tz = value.strip()
        if not tz:
            raise ValueError("timezone must not be empty")
        if len(tz) > 64:
            raise ValueError("timezone must be at most 64 characters")
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            raise ValueError("timezone must be a valid IANA timezone identifier")
        return tz

    @field_validator("date_format")
    @classmethod
    def validate_date_format(cls, value: str | None) -> str | None:
        if value is None:
            return value
        fmt = value.strip()
        if fmt != "YYYY-MM-DD":
            raise ValueError("date_format must be exactly \"YYYY-MM-DD\"")
        return fmt
