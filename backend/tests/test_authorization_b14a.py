from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_active_staff_user
from app.core.authorization import (
    has_global_role,
    require_global_roles,
    require_platform_admin,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.base import Base
from app.models.staff_user import StaffUser


@pytest.fixture()
def authz_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    app = None
    try:
        Base.metadata.create_all(bind=engine)
        app = create_app()

        @app.get("/protected-admin", dependencies=[Depends(require_platform_admin)])
        def protected_admin():
            return {"ok": True, "scope": "admin"}

        @app.get(
            "/protected-admin-manager",
            dependencies=[Depends(require_global_roles("administrator", "manager"))],
        )
        def protected_admin_manager():
            return {"ok": True, "scope": "admin-or-manager"}

        @app.get(
            "/protected-manager-viewer",
            dependencies=[Depends(require_global_roles("manager", "viewer"))],
        )
        def protected_manager_viewer():
            return {"ok": True, "scope": "manager-or-viewer"}

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            yield client, TestingSessionLocal, engine
    finally:
        try:
            if app is not None:
                app.dependency_overrides.clear()
        finally:
            engine.dispose()


def _create_staff(
    session_factory,
    *,
    email="staff@example.com",
    full_name="Staff User",
    password="correct-horse-battery-staple",
    global_role="viewer",
    status="Active",
    password_hash=None,
):
    with session_factory() as db:
        user = StaffUser(
            email=email,
            full_name=full_name,
            password_hash=password_hash if password_hash is not None else hash_password(password),
            global_role=global_role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return str(user.id), user.email


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _assert_generic_401(resp):
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"
    assert resp.headers.get("www-authenticate") == "Bearer"


def _assert_generic_403(resp):
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["message"] == "Forbidden."
    assert body["error"]["code"] == "HTTP_403"


# A. Global role decisions


def test_administrator_allowed_by_require_platform_admin(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="admin@example.com", global_role="administrator")
    resp = client.get("/protected-admin", headers=_auth_headers(user_id))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "scope": "admin"}


def test_manager_denied_by_require_platform_admin_with_generic_403(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="manager@example.com", global_role="manager")
    resp = client.get("/protected-admin", headers=_auth_headers(user_id))
    _assert_generic_403(resp)


def test_viewer_denied_by_require_platform_admin_with_generic_403(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="viewer@example.com", global_role="viewer")
    resp = client.get("/protected-admin", headers=_auth_headers(user_id))
    _assert_generic_403(resp)


def test_manager_allowed_when_explicitly_included_in_require_global_roles(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="manager2@example.com", global_role="manager")
    resp = client.get("/protected-admin-manager", headers=_auth_headers(user_id))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "scope": "admin-or-manager"}


def test_multiple_allowed_roles_behave_correctly(authz_client):
    client, sf, _ = authz_client
    manager_id, _ = _create_staff(sf, email="mv-manager@example.com", global_role="manager")
    viewer_id, _ = _create_staff(sf, email="mv-viewer@example.com", global_role="viewer")
    admin_id, _ = _create_staff(sf, email="mv-admin@example.com", global_role="administrator")

    allowed_manager = client.get("/protected-manager-viewer", headers=_auth_headers(manager_id))
    assert allowed_manager.status_code == 200
    assert allowed_manager.json() == {"ok": True, "scope": "manager-or-viewer"}

    allowed_viewer = client.get("/protected-manager-viewer", headers=_auth_headers(viewer_id))
    assert allowed_viewer.status_code == 200
    assert allowed_viewer.json() == {"ok": True, "scope": "manager-or-viewer"}

    denied_admin = client.get("/protected-manager-viewer", headers=_auth_headers(admin_id))
    _assert_generic_403(denied_admin)


def test_empty_allow_list_raises_value_error():
    with pytest.raises(ValueError, match="At least one allowed global role must be provided"):
        require_global_roles()


@pytest.mark.parametrize("invalid_role", ["owner", "Administrator", "admin", " manager ", "", "unknown"])
def test_invalid_allowed_role_arguments_outside_canonical_vocabulary_raise_value_error(invalid_role):
    # Approved policy: canonical global roles are exactly administrator, manager, viewer
    # and invalid allowed-role arguments outside this vocabulary raise ValueError.
    with pytest.raises(ValueError):
        require_global_roles(invalid_role)


# B. Authentication versus authorization


def test_missing_bearer_token_returns_generic_401_not_403(authz_client):
    client, _, _ = authz_client
    resp = client.get("/protected-admin")
    _assert_generic_401(resp)


def test_invalid_token_returns_generic_401_not_403(authz_client):
    client, _, _ = authz_client
    resp = client.get("/protected-admin", headers={"Authorization": "Bearer not-a-jwt"})
    _assert_generic_401(resp)


def test_valid_token_for_nonexistent_user_returns_generic_401_not_403(authz_client):
    client, _, _ = authz_client
    resp = client.get("/protected-admin", headers=_auth_headers(str(uuid.uuid4())))
    _assert_generic_401(resp)


def test_inactive_user_returns_generic_401_not_403(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="inactive-authz@example.com", global_role="administrator", status="Active")
    token_headers = _auth_headers(user_id)
    with sf() as db:
        user = db.get(StaffUser, uuid.UUID(user_id))
        assert user is not None
        user.status = "Inactive"
        db.commit()

    resp = client.get("/protected-admin", headers=token_headers)
    _assert_generic_401(resp)


# C. Database role source and fail-closed behavior


def test_changing_database_global_role_after_jwt_issuance_changes_authorization_decision(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="role-change@example.com", global_role="administrator", status="Active")
    headers = _auth_headers(user_id)

    allowed_before = client.get("/protected-admin", headers=headers)
    assert allowed_before.status_code == 200

    with sf() as db:
        user = db.get(StaffUser, uuid.UUID(user_id))
        assert user is not None
        user.global_role = "viewer"
        db.commit()

    denied_after = client.get("/protected-admin", headers=headers)
    _assert_generic_403(denied_after)


def test_authorization_does_not_trust_role_claim_in_jwt_exact_claims_contract(authz_client):
    client, sf, _ = authz_client
    user_id, _ = _create_staff(sf, email="jwt-role@example.com", global_role="viewer", status="Active")
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "global_role": "administrator",  # unexpected claim; must not be trusted
    }
    token = jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")
    resp = client.get("/protected-admin", headers={"Authorization": f"Bearer {token}"})
    # Consistent with existing exact-claims token contract: unexpected claims are rejected (401), not trusted.
    _assert_generic_401(resp)


def test_unknown_database_role_denied_by_require_platform_admin_with_403(authz_client):
    client, sf, _ = authz_client
    # Isolated to this test: override the shared auth dependency to supply an authenticated
    # active user object with an unknown global_role. The protected route still uses
    # require_platform_admin, and production auth/DB code and constraints remain unchanged.
    app = client.app
    previous_override = app.dependency_overrides.get(get_current_active_staff_user)
    try:
        app.dependency_overrides[get_current_active_staff_user] = lambda: StaffUser(
            email="unknown-role@example.com",
            full_name="Unknown Role User",
            global_role="unknown_role",
            status="Active",
        )

        resp = client.get("/protected-admin")
        _assert_generic_403(resp)
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_current_active_staff_user, None)
        else:
            app.dependency_overrides[get_current_active_staff_user] = previous_override
