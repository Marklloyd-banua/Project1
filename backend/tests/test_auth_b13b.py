from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.base import Base
from app.models.staff_user import StaffUser


@pytest.fixture()
def auth_client():
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

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            yield client, TestingSessionLocal
    finally:
        try:
            if app is not None:
                app.dependency_overrides.clear()
        finally:
            engine.dispose()


def _create_staff(session_factory, *, email="admin@example.com", full_name="Admin", password="correct-horse-battery-staple", global_role="administrator", status="Active", password_hash=None):
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


def test_login_success_returns_bearer_token(auth_client):
    client, sf = auth_client
    _create_staff(sf, email="admin@example.com", status="Active")
    resp = client.post("/api/v1/auth/login", json={"email": "  Admin@Example.com ", "password": "correct-horse-battery-staple"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body.get("access_token"), str) and body["access_token"]


def test_login_rejects_wrong_password_with_generic_401(auth_client):
    client, sf = auth_client
    _create_staff(sf)
    resp = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password-12345"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"


def test_login_rejects_unknown_user_with_generic_401(auth_client):
    client, _ = auth_client
    resp = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "correct-horse-battery-staple"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"


@pytest.mark.parametrize("inactive_status", ["Inactive", "Suspended", "Disabled", "Pending", "active", "ACTIVE", ""])
def test_login_rejects_non_active_status_with_generic_401(auth_client, inactive_status):
    client, sf = auth_client
    # Empty status must be stored as-is; it must not be treated as Active.
    _create_staff(sf, email="inactive@example.com", status=inactive_status)
    resp = client.post("/api/v1/auth/login", json={"email": "inactive@example.com", "password": "correct-horse-battery-staple"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"


def test_auth_me_returns_current_user(auth_client):
    client, sf = auth_client
    user_id, email = _create_staff(sf, email="admin@example.com", full_name="Alice Admin")
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery-staple"})
    token = login.json()["access_token"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user_id
    assert body["email"] == email
    assert body["full_name"] == "Alice Admin"
    assert body["global_role"] == "administrator"
    assert body["status"] == "Active"


def test_auth_me_reloads_user_from_runtime_database(auth_client):
    client, sf = auth_client
    user_id, _ = _create_staff(sf, email="admin@example.com", status="Active")
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery-staple"})
    token = login.json()["access_token"]

    # Change status directly in DB after token issuance; /auth/me must reload and reject.
    with sf() as db:
        user = db.get(StaffUser, uuid.UUID(user_id))
        user.status = "Inactive"
        db.commit()

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"


def test_auth_me_rejects_missing_invalid_or_inactive_with_generic_401(auth_client):
    client, sf = auth_client
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"

    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"

    # Valid token for non-existent user
    token = create_access_token(str(uuid.uuid4()))
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"

    user_id, _ = _create_staff(sf, email="inactive2@example.com", status="Suspended")
    token = create_access_token(user_id)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"


def test_auth_me_rejects_malformed_uuid_subject_with_generic_401(auth_client):
    client, _ = auth_client
    token = create_access_token("not-a-uuid")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"
    serialized = str(body).lower()
    assert "uuid" not in serialized
    assert "valueerror" not in serialized
    assert "traceback" not in serialized
    assert "not-a-uuid" not in serialized


def test_request_validation_errors_sanitized_to_loc_msg_type_only(auth_client):
    client, _ = auth_client
    resp = client.post("/api/v1/auth/login", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    errors = body["error"]["details"]["errors"]
    assert isinstance(errors, list) and errors
    for err in errors:
        assert set(err.keys()) == {"loc", "msg", "type"}
        # Ensure no raw ctx/input/url or other fields leak
        assert "ctx" not in err
        assert "input" not in err
        assert "url" not in err


def test_login_rejects_staff_with_null_password_hash_with_generic_401(auth_client):
    client, sf = auth_client
    user_id, email = _create_staff(sf, email="nullhash@example.com")
    with sf() as db:
        user = db.get(StaffUser, uuid.UUID(user_id))
        user.password_hash = None
        db.commit()

    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"
    serialized = str(body).lower()
    assert "password" not in serialized
    assert "hash" not in serialized
    assert "traceback" not in serialized
    assert "exception" not in serialized


def test_login_rejects_staff_with_malformed_password_hash_with_generic_401(auth_client):
    client, sf = auth_client
    malformed_hash = "not-a-valid-argon2-hash"
    _, email = _create_staff(
        sf,
        email="badhash@example.com",
        password_hash=malformed_hash,
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"
    serialized = str(body).lower()
    assert "argon2" not in serialized
    assert "traceback" not in serialized
    assert "exception" not in serialized
    assert malformed_hash.lower() not in serialized
    assert "password_hash" not in serialized
    assert "hash" not in serialized
