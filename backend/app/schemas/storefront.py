from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class StorefrontSettingsResponse(BaseModel):
    id: UUID
    store_id: UUID
    is_published: bool
    theme: dict[str, Any] | None
    social_links: dict[str, Any] | None
    contact_email: str | None
    primary_color: str | None
    created_at: datetime
    updated_at: datetime
