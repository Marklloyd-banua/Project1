"""Reusable helpers for B1.6 PostgreSQL-backed HTTP API integration tests.

Scope: test-only seed/auth/assert utilities for use with the existing verified
`backend/tests/integration_pg/conftest.py` fixture (disposable PostgreSQL DB,
Alembic head, per-test reset, dependency-overridden get_db). This module does not
modify fixture lifecycle, application wiring, schemas, models, or DB behavior.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.security import create_access_token, hash_password
from app.models.staff_user import StaffUser
from app.models.store import Store, StoreMembership


DEFAULT_PASSWORD = "correct-horse-battery-staple"


def create_staff(
    session_factory: sessionmaker[Session],
    *,
    email: str = "staff@example.com",
    full_name: str = "Staff User",
    password: str = DEFAULT_PASSWORD,
    password_hash: str | None = None,
    global_role: str = "viewer",
    status: str = "Active",
) -> dict[str, Any]:
    """Create and persist a StaffUser; returns id/email and key fields."""
    with session_factory() as db:
        user = StaffUser(
            email=email,
            full_name=full_name,
            password_hash=(
                password_hash if password_hash is not None else hash_password(password)
            ),
            global_role=global_role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "global_role": user.global_role,
            "status": user.status,
        }


def create_store(
    session_factory: sessionmaker[Session],
    *,
    name: str = "Store A",
    owner: str = "Owner Name",
    domain: str,
    **extra: Any,
) -> dict[str, Any]:
    """Create and persist a Store; returns id/domain/name."""
    with session_factory() as db:
        store = Store(name=name, owner=owner, domain=domain, **extra)
        db.add(store)
        db.commit()
        db.refresh(store)
        return {"id": str(store.id), "domain": store.domain, "name": store.name}


def create_store_membership(
    session_factory: sessionmaker[Session],
    *,
    store_id: str,
    staff_user_id: str,
    role: str,
) -> dict[str, Any]:
    """Create and persist a StoreMembership; returns id/role."""
    with session_factory() as db:
        membership = StoreMembership(
            store_id=uuid.UUID(store_id),
            staff_user_id=uuid.UUID(staff_user_id),
            role=role,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)
        return {
            "id": str(membership.id),
            "store_id": str(membership.store_id),
            "staff_user_id": str(membership.staff_user_id),
            "role": membership.role,
        }


def auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def auth_headers_for_token(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_generic_401(resp) -> None:
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"
    assert resp.headers.get("www-authenticate") == "Bearer"


def assert_generic_403(resp) -> None:
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["message"] == "Forbidden."
    assert body["error"]["code"] == "HTTP_403"


def assert_generic_404(resp) -> None:
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("error", {}).get("code") == "HTTP_404"
