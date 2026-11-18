"""B1.6 Step 2 (batch 1): PostgreSQL-backed HTTP API integration tests for authentication.

Covers (per actual endpoint contracts):
- POST /api/v1/auth/login success and invalid credential/inactive cases (generic 401)
- GET /api/v1/auth/me authenticated success and auth-failure cases (generic 401)
  including missing/malformed/invalid/expired/invalid-subject/nonexistent/inactive tokens

Uses the existing verified B1.6 disposable PostgreSQL fixture without modification.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.staff_user import StaffUser

from .helpers_pg import (
    DEFAULT_PASSWORD,
    assert_generic_401,
    auth_headers,
    auth_headers_for_token,
    create_staff,
)


# Ensure required auth settings are available for token creation/validation in this module.
# Values are deterministic test-only non-production placeholders; original env is restored.
_TEST_AUTH_ENV = {
    "AUTH_JWT_SECRET": "b16-integration-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.integration.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-integration-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}


@pytest.fixture(autouse=True)
def _b16_auth_env():
    previous = {k: os.environ.get(k) for k in _TEST_AUTH_ENV}
    for k, v in _TEST_AUTH_ENV.items():
        os.environ[k] = v
    try:
        get_settings.cache_clear()
    except Exception:
        pass
    yield
    for k, old in previous.items():
        if old is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old
    try:
        get_settings.cache_clear()
    except Exception:
        pass


LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"


def _assert_no_sensitive_auth_leak(resp, *extra_forbidden: str) -> None:
    serialized = resp.text.lower()
    for token in (
        "password_hash",
        "traceback",
        "exception",
        "argon2",
    ):
        assert token not in serialized
    for token in extra_forbidden:
        assert token.lower() not in serialized


def test_login_success_returns_bearer_token(pg_api_client, pg_api_session_factory):
    create_staff(pg_api_session_factory, email="admin@example.com", status="Active")
    resp = pg_api_client.post(
        LOGIN_URL,
        json={"email": "  Admin@Example.com ", "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body.get("access_token"), str) and body["access_token"]


def test_login_rejects_wrong_password_with_generic_401(pg_api_client, pg_api_session_factory):
    create_staff(pg_api_session_factory, email="admin@example.com", status="Active")
    resp = pg_api_client.post(
        LOGIN_URL,
        json={"email": "admin@example.com", "password": "wrong-password-12345"},
    )
    assert_generic_401(resp)


def test_login_rejects_unknown_user_with_generic_401(pg_api_client):
    resp = pg_api_client.post(
        LOGIN_URL,
        json={"email": "nobody@example.com", "password": DEFAULT_PASSWORD},
    )
    assert_generic_401(resp)


@pytest.mark.parametrize(
    "inactive_status",
    ["Inactive", "Suspended", "Disabled", "Pending", "active", "ACTIVE", ""],
)
def test_login_rejects_non_active_status_with_generic_401(
    pg_api_client, pg_api_session_factory, inactive_status
):
    # Empty/variant statuses must not be treated as Active.
    email = f"user-{abs(hash(inactive_status)) % 100000}@example.com"
    create_staff(pg_api_session_factory, email=email, status=inactive_status)
    resp = pg_api_client.post(LOGIN_URL, json={"email": email, "password": DEFAULT_PASSWORD})
    assert_generic_401(resp)


def test_login_rejects_null_password_hash_with_generic_401(pg_api_client, pg_api_session_factory):
    staff = create_staff(pg_api_session_factory, email="nullhash@example.com", status="Active")
    with pg_api_session_factory() as db:
        user = db.get(StaffUser, uuid.UUID(staff["id"]))
        assert user is not None
        user.password_hash = None
        db.commit()

    resp = pg_api_client.post(
        LOGIN_URL,
        json={"email": staff["email"], "password": DEFAULT_PASSWORD},
    )
    assert_generic_401(resp)
    _assert_no_sensitive_auth_leak(resp)


def test_login_rejects_malformed_password_hash_with_generic_401(pg_api_client, pg_api_session_factory):
    malformed_hash = "not-a-valid-argon2-hash"
    staff = create_staff(
        pg_api_session_factory,
        email="badhash@example.com",
        password_hash=malformed_hash,
        status="Active",
    )
    resp = pg_api_client.post(
        LOGIN_URL,
        json={"email": staff["email"], "password": DEFAULT_PASSWORD},
    )
    assert_generic_401(resp)
    _assert_no_sensitive_auth_leak(resp, malformed_hash, "hash")


def test_auth_me_returns_current_active_user(pg_api_client, pg_api_session_factory):
    staff = create_staff(
        pg_api_session_factory,
        email="alice@example.com",
        full_name="Alice Admin",
        global_role="administrator",
        status="Active",
    )
    login = pg_api_client.post(
        LOGIN_URL, json={"email": "alice@example.com", "password": DEFAULT_PASSWORD}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    resp = pg_api_client.get(ME_URL, headers=auth_headers_for_token(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "id": staff["id"],
        "email": staff["email"],
        "full_name": "Alice Admin",
        "global_role": "administrator",
        "status": "Active",
    }


def test_auth_me_rejects_missing_bearer_with_generic_401(pg_api_client):
    resp = pg_api_client.get(ME_URL)
    assert_generic_401(resp)


def test_auth_me_rejects_malformed_bearer_token_with_generic_401(pg_api_client):
    resp = pg_api_client.get(ME_URL, headers=auth_headers_for_token("not-a-jwt"))
    assert_generic_401(resp)


def test_auth_me_rejects_valid_token_for_nonexistent_user_with_generic_401(pg_api_client):
    token = create_access_token(str(uuid.uuid4()))
    resp = pg_api_client.get(ME_URL, headers=auth_headers_for_token(token))
    assert_generic_401(resp)


def test_auth_me_rejects_inactive_user_with_generic_401(pg_api_client, pg_api_session_factory):
    staff = create_staff(pg_api_session_factory, email="inactive-me@example.com", status="Active")
    headers = auth_headers(staff["id"])
    with pg_api_session_factory() as db:
        user = db.get(StaffUser, uuid.UUID(staff["id"]))
        assert user is not None
        user.status = "Inactive"
        db.commit()

    resp = pg_api_client.get(ME_URL, headers=headers)
    assert_generic_401(resp)


def test_auth_me_rejects_non_active_status_token_subject_with_generic_401(
    pg_api_client, pg_api_session_factory
):
    staff = create_staff(pg_api_session_factory, email="suspended-me@example.com", status="Suspended")
    resp = pg_api_client.get(ME_URL, headers=auth_headers(staff["id"]))
    assert_generic_401(resp)


def test_auth_me_rejects_malformed_uuid_subject_with_generic_401(pg_api_client):
    # Token is well-formed/signed with valid claims contract but subject is not a UUID.
    token = create_access_token("not-a-uuid")
    resp = pg_api_client.get(ME_URL, headers=auth_headers_for_token(token))
    assert_generic_401(resp)
    serialized = resp.text.lower()
    assert "uuid" not in serialized
    assert "valueerror" not in serialized
    assert "traceback" not in serialized
    assert "not-a-uuid" not in serialized


def test_auth_me_rejects_expired_token_with_generic_401(pg_api_client, pg_api_session_factory):
    staff = create_staff(pg_api_session_factory, email="expired@example.com", status="Active")
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": staff["id"],
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": int((now - timedelta(minutes=30)).timestamp()),
        "exp": int((now - timedelta(minutes=5)).timestamp()),
    }
    expired_token = jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")
    resp = pg_api_client.get(ME_URL, headers=auth_headers_for_token(expired_token))
    assert_generic_401(resp)
