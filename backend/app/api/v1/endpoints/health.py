from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/health", tags=["health"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness/basic health: process is running and can respond over HTTP."""
    return {
        "ok": True,
        "status": "healthy",
        "service": settings.app_name,
        "environment": settings.app_env,
        "timestamp": _now_iso(),
    }


@router.get("/ready")
async def readiness(settings: Settings = Depends(get_settings)) -> dict:
    """Readiness: HTTP/config plus a real database connectivity probe (Phase 1).

    Contract:
    - Probe succeeds: HTTP 200, ok=True, status="ready", checks.database="connected".
    - Probe fails:    HTTP 503, ok=False, status="not_ready", checks.database="error".

    The database failure token is a generic constant — never exception text, driver
    names, hostnames, usernames, or connection strings. Technical details are logged
    server-side only. Auth remains not implemented (Phase 3).
    """
    checks = {
        "http": True,
        "config": bool(settings.api_v1_prefix),
        "database": _database_check(),
        "auth": "not_configured",
    }
    db_ready = checks["database"] == "connected"
    payload = {
        "ok": db_ready,
        "status": "ready" if db_ready else "not_ready",
        "service": settings.app_name,
        "environment": settings.app_env,
        "timestamp": _now_iso(),
        "checks": checks,
        "note": (
            "Readiness reflects HTTP/config/database connectivity. Auth is not implemented "
            "in this phase. Database failures are reported generically; details are in server logs."
        ),
    }
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=200 if db_ready else 503, content=payload)


def _database_check() -> str:
    """Run the no-schema connectivity probe and map the result to a safe constant.

    "not_configured" is no longer used as a default: Phase 1 always configures a database
    URL (SQLite dev default), so the result is "connected" or "error". The generic "error"
    token intentionally carries no technical detail; full diagnostics stay in server logs.
    """
    from app.core.db import engine, probe_database

    ok, _reason = probe_database(engine)  # reason is generic; details already logged.
    return "connected" if ok else "error"
