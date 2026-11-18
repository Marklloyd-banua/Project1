"""Shared pagination conventions for B1.5B read/list endpoints.

These primitives are intended for B1.5B list APIs:
- page: 1-based page number, default 1, minimum 1.
- page_size: items per page, default 20, minimum 1, maximum 100.
- Invalid pagination values must fail request validation with HTTP 422.
- List responses use: {"items": [...], "total": <int>, "page": <int>, "page_size": <int>}.
- "total" is the full matching record count before pagination.
- Out-of-range pages return HTTP 200 with empty items and accurate total.

Monetary Decimal serialization convention for future B1.5B responses:
serialize Decimal monetary values as JSON strings (preserve precision; never float).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Validated pagination query parameters for B1.5B list endpoints."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


def get_pagination_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginationParams:
    """FastAPI dependency for B1.5B pagination query params (422 on invalid)."""
    return PaginationParams(page=page, page_size=page_size)


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard B1.5B list envelope."""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
