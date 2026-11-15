from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_response(
    message: str,
    code: str,
    details: Optional[Dict[str, Any]] = None,
    status_code: int = 400,
    headers: Optional[Mapping[str, str]] = None,
) -> JSONResponse:
    payload: Dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(
            message=detail,
            code=f"HTTP_{exc.status_code}",
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        sanitized_errors = [
            {
                "loc": error.get("loc", []),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return error_response(
            message="Request validation failed.",
            code="VALIDATION_ERROR",
            details={"errors": sanitized_errors},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
        # Avoid leaking internal details. Logging/observability can be added in a later phase.
        return error_response(
            message="An unexpected server error occurred.",
            code="INTERNAL_SERVER_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
