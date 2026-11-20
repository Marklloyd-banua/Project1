"""PostgreSQL-backed HTTP API integration tests for GET /api/v1/auth/me/stores.

Covers approved store-discovery contract:
- Active authenticated staff receives only their actual StoreMembership-backed stores.
- Exact response fields/order: store_id, store_name, store_status, membership_role.
- Memberships included regardless of Store.status.
- Deterministic ordering by Store.name ASC, Store.id ASC.
- Empty memberships => {"items": []}.
- Platform administrator without membership => {"items": []} (no inference from global_role).
- Other users' memberships/unrelated stores excluded; no extra private store fields.
- Auth failures (inactive staff, missing/invalid/expired bearer tokens) => generic 401.
- Existing /auth/login and /auth/me behavior remains unchanged (sanity checks).

Uses existing verified disposable PostgreSQL fixture/helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import create_access_token

from .helpers_pg import (
    DEFAULT_PASSWORD,
    assert_generic_401,
    auth_headers,
    auth_headers_for_token,
    create_staff,
    create_store,
    create_store_membership,
)


_TEST_AUTH_ENV = {
    "AUTH_JWT_SECRET": "b16-auth-me-stores-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.auth-me-stores.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-auth-me-stores-test-audience",
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


ME_STORES_URL = "/api/v1/auth/me/stores"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"


def _assert_item_contract(item: dict) -> None:
    assert set(item.keys()) == {
        "store_id",
        "store_name",
        "store_status",
        "membership_role",
    }
    uuid.UUID(item["store_id"])
    assert isinstance(item["store_name"], str)
    assert isinstance(item["store_status"], str)
    assert item["membership_role"] in {"owner", "manager", "viewer"}


def test_active_user_with_multiple_memberships_returns_only_own_stores_with_exact_fields(
    pg_api_client, pg_api_session_factory
):
    user = create_staff(
        pg_api_session_factory,
        email="multi@example.com",
        full_name="Multi User",
        global_role="viewer",
        status="Active",
    )
    other_user = create_staff(
        pg_api_session_factory,
        email="other@example.com",
        full_name="Other User",
        global_role="viewer",
        status="Active",
    )

    store_b = create_store(
        pg_api_session_factory,
        name="Beta Store",
        domain="beta-multi.example.com",
        status="Active",
    )
    store_a = create_store(
        pg_api_session_factory,
        name="Alpha Store",
        domain="alpha-multi.example.com",
        status="Suspended",
    )
    store_other = create_store(
        pg_api_session_factory,
        name="Gamma Store",
        domain="gamma-other.example.com",
        status="Active",
    )
    unrelated_store = create_store(
        pg_api_session_factory,
        name="Zeta Unrelated",
        domain="zeta-unrelated.example.com",
        status="Active",
    )

    create_store_membership(
        pg_api_session_factory,
        store_id=store_b["id"],
        staff_user_id=user["id"],
        role="manager",
    )
    create_store_membership(
        pg_api_session_factory,
        store_id=store_a["id"],
        staff_user_id=user["id"],
        role="owner",
    )
    # Other user's membership and unrelated store must be excluded.
    create_store_membership(
        pg_api_session_factory,
        store_id=store_other["id"],
        staff_user_id=other_user["id"],
        role="viewer",
    )
    create_store_membership(
        pg_api_session_factory,
        store_id=store_b["id"],
        staff_user_id=other_user["id"],
        role="owner",
    )

    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers(user["id"]))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items"}
    items = body["items"]
    assert len(items) == 2
    for item in items:
        _assert_item_contract(item)
        assert "store_domain" not in item
        assert "mrr" not in item
        assert "plan" not in item
        assert "currency" not in item
        assert "owner" not in item
        assert "contact_email" not in item
        assert "phone_number" not in item
        assert "business_address" not in item
        assert "description" not in item

    # Only user's actual memberships, regardless of Store.status.
    assert items == [
        {
            "store_id": store_a["id"],
            "store_name": "Alpha Store",
            "store_status": "Suspended",
            "membership_role": "owner",
        },
        {
            "store_id": store_b["id"],
            "store_name": "Beta Store",
            "store_status": "Active",
            "membership_role": "manager",
        },
    ]
    returned_ids = {item["store_id"] for item in items}
    assert unrelated_store["id"] not in returned_ids
    assert store_other["id"] not in returned_ids


def test_role_values_owner_manager_viewer_are_returned_correctly(
    pg_api_client, pg_api_session_factory
):
    user = create_staff(
        pg_api_session_factory,
        email="roles@example.com",
        global_role="viewer",
        status="Active",
    )
    owner_store = create_store(
        pg_api_session_factory, name="Owner Store", domain="owner-role.example.com"
    )
    manager_store = create_store(
        pg_api_session_factory, name="Manager Store", domain="manager-role.example.com"
    )
    viewer_store = create_store(
        pg_api_session_factory, name="Viewer Store", domain="viewer-role.example.com"
    )

    create_store_membership(
        pg_api_session_factory, store_id=owner_store["id"], staff_user_id=user["id"], role="owner"
    )
    create_store_membership(
        pg_api_session_factory,
        store_id=manager_store["id"],
        staff_user_id=user["id"],
        role="manager",
    )
    create_store_membership(
        pg_api_session_factory,
        store_id=viewer_store["id"],
        staff_user_id=user["id"],
        role="viewer",
    )

    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers(user["id"]))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    for item in items:
        _assert_item_contract(item)
    roles_by_store = {item["store_id"]: item["membership_role"] for item in items}
    assert roles_by_store[owner_store["id"]] == "owner"
    assert roles_by_store[manager_store["id"]] == "manager"
    assert roles_by_store[viewer_store["id"]] == "viewer"


def test_no_memberships_returns_exact_empty_items(pg_api_client, pg_api_session_factory):
    user = create_staff(
        pg_api_session_factory,
        email="nomemberships@example.com",
        global_role="viewer",
        status="Active",
    )
    # Unrelated store/membership must not affect result.
    other = create_staff(
        pg_api_session_factory,
        email="someoneelse@example.com",
        global_role="viewer",
        status="Active",
    )
    store = create_store(
        pg_api_session_factory, name="Foreign", domain="foreign-empty.example.com"
    )
    create_store_membership(
        pg_api_session_factory, store_id=store["id"], staff_user_id=other["id"], role="owner"
    )

    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers(user["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_platform_administrator_without_membership_returns_empty_list(
    pg_api_client, pg_api_session_factory
):
    # global_role must never imply store membership/access.
    admin = create_staff(
        pg_api_session_factory,
        email="admin-nomembership@example.com",
        global_role="administrator",
        status="Active",
    )
    other = create_staff(
        pg_api_session_factory,
        email="member-other@example.com",
        global_role="viewer",
        status="Active",
    )
    store = create_store(
        pg_api_session_factory, name="Other Store", domain="other-admin-empty.example.com"
    )
    create_store_membership(
        pg_api_session_factory, store_id=store["id"], staff_user_id=other["id"], role="owner"
    )

    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers(admin["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_deterministic_ordering_by_store_name_then_uuid(pg_api_client, pg_api_session_factory):
    user = create_staff(
        pg_api_session_factory,
        email="ordering@example.com",
        global_role="viewer",
        status="Active",
    )
    store_c = create_store(
        pg_api_session_factory, name="Charlie", domain="charlie-order.example.com"
    )
    store_a = create_store(
        pg_api_session_factory, name="Alpha", domain="alpha-order.example.com"
    )
    same_name_1 = create_store(
        pg_api_session_factory, name="Bravo", domain="bravo-1-order.example.com"
    )
    same_name_2 = create_store(
        pg_api_session_factory, name="Bravo", domain="bravo-2-order.example.com"
    )

    for store, role in [
        (store_c, "viewer"),
        (same_name_2, "manager"),
        (store_a, "owner"),
        (same_name_1, "viewer"),
    ]:
        create_store_membership(
            pg_api_session_factory,
            store_id=store["id"],
            staff_user_id=user["id"],
            role=role,
        )

    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers(user["id"]))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 4
    for item in items:
        _assert_item_contract(item)

    expected_bravo_ids = sorted([same_name_1["id"], same_name_2["id"]])
    expected = [
        (store_a["id"], "Alpha"),
        (expected_bravo_ids[0], "Bravo"),
        (expected_bravo_ids[1], "Bravo"),
        (store_c["id"], "Charlie"),
    ]
    actual = [(item["store_id"], item["store_name"]) for item in items]
    assert actual == expected


def test_inactive_staff_returns_generic_401(pg_api_client, pg_api_session_factory):
    user = create_staff(
        pg_api_session_factory,
        email="inactive-stores@example.com",
        global_role="viewer",
        status="Active",
    )
    store = create_store(
        pg_api_session_factory, name="Store", domain="inactive-auth.example.com"
    )
    create_store_membership(
        pg_api_session_factory, store_id=store["id"], staff_user_id=user["id"], role="owner"
    )
    headers = auth_headers(user["id"])

    # Become inactive after token issuance; dependency reloads and rejects.
    from app.models.staff_user import StaffUser

    with pg_api_session_factory() as db:
        row = db.get(StaffUser, uuid.UUID(user["id"]))
        assert row is not None
        row.status = "Inactive"
        db.commit()

    resp = pg_api_client.get(ME_STORES_URL, headers=headers)
    assert_generic_401(resp)


def test_missing_bearer_token_returns_generic_401(pg_api_client):
    resp = pg_api_client.get(ME_STORES_URL)
    assert_generic_401(resp)


def test_invalid_and_expired_tokens_return_generic_401(pg_api_client, pg_api_session_factory):
    # Invalid/malformed bearer
    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers_for_token("not-a-jwt"))
    assert_generic_401(resp)

    # Expired token for existing active user
    user = create_staff(
        pg_api_session_factory,
        email="expired-stores@example.com",
        global_role="viewer",
        status="Active",
    )
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["id"],
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": int((now - timedelta(minutes=30)).timestamp()),
        "exp": int((now - timedelta(minutes=5)).timestamp()),
    }
    expired_token = jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")
    resp = pg_api_client.get(ME_STORES_URL, headers=auth_headers_for_token(expired_token))
    assert_generic_401(resp)


def test_existing_auth_login_and_me_behavior_unchanged(pg_api_client, pg_api_session_factory):
    user = create_staff(
        pg_api_session_factory,
        email="unchanged@example.com",
        full_name="Unchanged User",
        global_role="administrator",
        status="Active",
    )

    login = pg_api_client.post(
        LOGIN_URL,
        json={"email": "  Unchanged@Example.com ", "password": DEFAULT_PASSWORD},
    )
    assert login.status_code == 200
    login_body = login.json()
    assert login_body["token_type"] == "bearer"
    assert isinstance(login_body.get("access_token"), str) and login_body["access_token"]

    me = pg_api_client.get(ME_URL, headers=auth_headers_for_token(login_body["access_token"]))
    assert me.status_code == 200
    assert me.json() == {
        "id": user["id"],
        "email": user["email"],
        "full_name": "Unchanged User",
        "global_role": "administrator",
        "status": "Active",
    }
