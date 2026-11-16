from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authorization import require_platform_admin
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.core.store_authorization import (
    get_store_membership,
    has_store_role,
    require_store_member,
    require_store_owner,
    require_store_owner_or_manager,
)
from app.main import create_app
from app.models.base import Base
from app.models.staff_user import StaffUser
from app.models.store import Store, StoreMembership


@pytest.fixture()
def store_authz_client():
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

        @app.get("/stores/{store_id}/read-member")
        def read_member(membership: StoreMembership = Depends(require_store_member)):
            return {"ok": True, "scope": "read-member", "role": membership.role}

        @app.head("/stores/{store_id}/read-member-head")
        def read_member_head(membership: StoreMembership = Depends(require_store_member)):
            return None

        @app.get("/stores/{store_id}/read-owner-manager")
        def read_owner_manager(
            membership: StoreMembership = Depends(require_store_owner_or_manager),
        ):
            return {"ok": True, "scope": "read-owner-manager", "role": membership.role}

        @app.post("/stores/{store_id}/op-owner-manager")
        def op_owner_manager(
            membership: StoreMembership = Depends(require_store_owner_or_manager),
        ):
            return {"ok": True, "scope": "op-owner-manager", "role": membership.role}

        @app.put("/stores/{store_id}/op-owner-manager")
        def op_owner_manager_put(
            membership: StoreMembership = Depends(require_store_owner_or_manager),
        ):
            return {"ok": True, "scope": "op-owner-manager-put", "role": membership.role}

        @app.patch("/stores/{store_id}/op-owner-manager")
        def op_owner_manager_patch(
            membership: StoreMembership = Depends(require_store_owner_or_manager),
        ):
            return {"ok": True, "scope": "op-owner-manager-patch", "role": membership.role}

        @app.delete("/stores/{store_id}/op-owner-manager")
        def op_owner_manager_delete(
            membership: StoreMembership = Depends(require_store_owner_or_manager),
        ):
            return {"ok": True, "scope": "op-owner-manager-delete", "role": membership.role}

        @app.post("/stores/{store_id}/op-owner")
        def op_owner(membership: StoreMembership = Depends(require_store_owner)):
            return {"ok": True, "scope": "op-owner", "role": membership.role}

        @app.get("/protected-admin-b14a-regression", dependencies=[Depends(require_platform_admin)])
        def protected_admin_b14a_regression():
            return {"ok": True, "scope": "admin-regression"}

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
            password_hash=(
                password_hash if password_hash is not None else hash_password(password)
            ),
            global_role=global_role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return str(user.id), user.email


def _create_store(session_factory, *, name="Store", owner="Owner", domain):
    with session_factory() as db:
        store = Store(name=name, owner=owner, domain=domain)
        db.add(store)
        db.commit()
        db.refresh(store)
        return str(store.id)


def _create_membership(session_factory, *, store_id: str, staff_user_id: str, role: str):
    with session_factory() as db:
        membership = StoreMembership(
            store_id=uuid.UUID(store_id),
            staff_user_id=uuid.UUID(staff_user_id),
            role=role,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)
        return str(membership.id)


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _assert_generic_401(resp):
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Invalid credentials."
    assert body["error"]["code"] == "HTTP_401"
    assert resp.headers.get("www-authenticate") == "Bearer"


def _assert_generic_403(resp, allow_empty_body: bool = False):
    assert resp.status_code == 403
    if allow_empty_body and not resp.content:
        return
    body = resp.json()
    assert body["error"]["message"] == "Forbidden."
    assert body["error"]["code"] == "HTTP_403"


# Authentication: store-protected routes must preserve 401 semantics


def test_missing_bearer_token_returns_generic_401(store_authz_client):
    client, _ = store_authz_client
    resp = client.get(f"/stores/{uuid.uuid4()}/read-member")
    _assert_generic_401(resp)


def test_invalid_token_returns_generic_401(store_authz_client):
    client, _ = store_authz_client
    resp = client.get(
        f"/stores/{uuid.uuid4()}/read-member",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    _assert_generic_401(resp)


def test_malformed_uuid_subject_returns_generic_401(store_authz_client):
    client, _ = store_authz_client
    token = create_access_token("not-a-uuid")
    resp = client.get(
        f"/stores/{uuid.uuid4()}/read-member",
        headers={"Authorization": f"Bearer {token}"},
    )
    _assert_generic_401(resp)


def test_nonexistent_user_returns_generic_401(store_authz_client):
    client, _ = store_authz_client
    resp = client.get(
        f"/stores/{uuid.uuid4()}/read-member",
        headers=_auth_headers(str(uuid.uuid4())),
    )
    _assert_generic_401(resp)


def test_inactive_user_returns_generic_401(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="inactive@example.com", status="Active")
    store_id = _create_store(sf, domain="inactive-store.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_id, role="owner")
    headers = _auth_headers(user_id)
    with sf() as db:
        user = db.get(StaffUser, uuid.UUID(user_id))
        assert user is not None
        user.status = "Inactive"
        db.commit()

    resp = client.get(f"/stores/{store_id}/read-member", headers=headers)
    _assert_generic_401(resp)


# Membership and role permissions


def test_owner_member_can_read_and_operate(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="owner@example.com", global_role="viewer")
    store_id = _create_store(sf, domain="owner-store.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_id, role="owner")
    headers = _auth_headers(user_id)

    read_resp = client.get(f"/stores/{store_id}/read-member", headers=headers)
    assert read_resp.status_code == 200
    assert read_resp.json()["role"] == "owner"

    head_resp = client.head(f"/stores/{store_id}/read-member-head", headers=headers)
    assert head_resp.status_code == 200

    for method, path in [
        ("post", f"/stores/{store_id}/op-owner-manager"),
        ("put", f"/stores/{store_id}/op-owner-manager"),
        ("patch", f"/stores/{store_id}/op-owner-manager"),
        ("delete", f"/stores/{store_id}/op-owner-manager"),
        ("post", f"/stores/{store_id}/op-owner"),
    ]:
        resp = getattr(client, method)(path, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["role"] == "owner"


def test_manager_member_can_read_and_operate_non_owner_only(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="manager@example.com", global_role="viewer")
    store_id = _create_store(sf, domain="manager-store.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_id, role="manager")
    headers = _auth_headers(user_id)

    read_resp = client.get(f"/stores/{store_id}/read-member", headers=headers)
    assert read_resp.status_code == 200
    assert read_resp.json()["role"] == "manager"

    for method, path in [
        ("post", f"/stores/{store_id}/op-owner-manager"),
        ("put", f"/stores/{store_id}/op-owner-manager"),
        ("patch", f"/stores/{store_id}/op-owner-manager"),
        ("delete", f"/stores/{store_id}/op-owner-manager"),
    ]:
        resp = getattr(client, method)(path, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["role"] == "manager"

    denied_owner_only = client.post(f"/stores/{store_id}/op-owner", headers=headers)
    _assert_generic_403(denied_owner_only)


def test_viewer_member_can_read_but_cannot_operate(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="viewer@example.com", global_role="viewer")
    store_id = _create_store(sf, domain="viewer-store.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_id, role="viewer")
    headers = _auth_headers(user_id)

    read_resp = client.get(f"/stores/{store_id}/read-member", headers=headers)
    assert read_resp.status_code == 200
    assert read_resp.json()["role"] == "viewer"

    head_resp = client.head(f"/stores/{store_id}/read-member-head", headers=headers)
    assert head_resp.status_code == 200

    for method, path in [
        ("post", f"/stores/{store_id}/op-owner-manager"),
        ("put", f"/stores/{store_id}/op-owner-manager"),
        ("patch", f"/stores/{store_id}/op-owner-manager"),
        ("delete", f"/stores/{store_id}/op-owner-manager"),
        ("post", f"/stores/{store_id}/op-owner"),
    ]:
        resp = getattr(client, method)(path, headers=headers)
        _assert_generic_403(resp)


def test_active_non_member_denied_read_and_write(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="nonmember@example.com", global_role="viewer")
    store_id = _create_store(sf, domain="nonmember-store.example.com")
    headers = _auth_headers(user_id)

    _assert_generic_403(client.get(f"/stores/{store_id}/read-member", headers=headers))
    _assert_generic_403(
        client.head(f"/stores/{store_id}/read-member-head", headers=headers),
        allow_empty_body=True,
    )
    _assert_generic_403(client.post(f"/stores/{store_id}/op-owner-manager", headers=headers))


def test_member_of_different_store_denied_cross_store(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="cross@example.com", global_role="viewer")
    store_a = _create_store(sf, domain="store-a.example.com")
    store_b = _create_store(sf, domain="store-b.example.com")
    _create_membership(sf, store_id=store_a, staff_user_id=user_id, role="owner")
    headers = _auth_headers(user_id)

    _assert_generic_403(client.get(f"/stores/{store_b}/read-member", headers=headers))
    _assert_generic_403(client.post(f"/stores/{store_b}/op-owner-manager", headers=headers))


def test_platform_admin_without_membership_denied(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(
        sf, email="platform-admin@example.com", global_role="administrator"
    )
    store_id = _create_store(sf, domain="admin-nomember-store.example.com")
    headers = _auth_headers(user_id)

    _assert_generic_403(client.get(f"/stores/{store_id}/read-member", headers=headers))
    _assert_generic_403(client.post(f"/stores/{store_id}/op-owner-manager", headers=headers))


def test_valid_uuid_for_nonexistent_store_returns_generic_403(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="nostore@example.com", global_role="viewer")
    headers = _auth_headers(user_id)
    missing_store_id = str(uuid.uuid4())

    resp = client.get(f"/stores/{missing_store_id}/read-member", headers=headers)
    _assert_generic_403(resp)


def test_has_store_role_rejects_unknown_role():
    # Function-level helper check for unknown roles.
    assert has_store_role(SimpleNamespace(role="auditor"), "owner", "manager", "viewer") is False
    assert has_store_role(SimpleNamespace(role=""), "owner", "manager", "viewer") is False


def test_get_store_membership_rejects_unknown_role(store_authz_client):
    _, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="unknown-direct@example.com", global_role="viewer")
    store_id = _create_store(sf, domain="unknown-direct.example.com")

    class _Result:
        def __init__(self, membership):
            self._membership = membership

        def scalar_one_or_none(self):
            return self._membership

    # Build a minimal current user context without trusting JWT/request roles.
    current_user = SimpleNamespace(id=uuid.UUID(user_id))
    bad_membership = SimpleNamespace(
        store_id=uuid.UUID(store_id),
        staff_user_id=uuid.UUID(user_id),
        role="auditor",
    )
    fake_db = SimpleNamespace(execute=lambda *_args, **_kwargs: _Result(bad_membership))

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        get_store_membership(uuid.UUID(store_id), current_user=current_user, db=fake_db)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "Forbidden."


# Security and database trust


def test_membership_must_match_both_store_id_and_staff_user_id(store_authz_client):
    client, sf = store_authz_client
    user_a, _ = _create_staff(sf, email="usera@example.com")
    user_b, _ = _create_staff(sf, email="userb@example.com")
    store_id = _create_store(sf, domain="match-both.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_b, role="owner")

    # user_a has no membership even though store has a member
    resp = client.get(f"/stores/{store_id}/read-member", headers=_auth_headers(user_a))
    _assert_generic_403(resp)


def test_changing_membership_role_in_db_affects_subsequent_authorization(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="rolechange@example.com")
    store_id = _create_store(sf, domain="rolechange-store.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_id, role="owner")
    headers = _auth_headers(user_id)

    allowed = client.post(f"/stores/{store_id}/op-owner-manager", headers=headers)
    assert allowed.status_code == 200

    with sf() as db:
        membership = db.query(StoreMembership).filter(
            StoreMembership.store_id == uuid.UUID(store_id),
            StoreMembership.staff_user_id == uuid.UUID(user_id),
        ).one()
        membership.role = "viewer"
        db.commit()

    denied = client.post(f"/stores/{store_id}/op-owner-manager", headers=headers)
    _assert_generic_403(denied)


def test_no_role_accepted_from_jwt_claims_or_request_payload(store_authz_client):
    client, sf = store_authz_client
    user_id, _ = _create_staff(sf, email="jwtclaim@example.com", global_role="viewer")
    store_id = _create_store(sf, domain="jwtclaim-store.example.com")
    _create_membership(sf, store_id=store_id, staff_user_id=user_id, role="viewer")
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "store_role": "owner",
        "role": "owner",
        "global_role": "administrator",
    }
    token = jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}

    # Existing exact-claims contract rejects unexpected claims -> 401, proving claims not trusted.
    resp = client.post(f"/stores/{store_id}/op-owner-manager", headers=headers)
    _assert_generic_401(resp)

    # Also verify request payload cannot grant access when properly authenticated.
    valid_headers = _auth_headers(user_id)
    resp_payload = client.post(
        f"/stores/{store_id}/op-owner-manager",
        headers=valid_headers,
        json={"role": "owner", "store_role": "owner"},
    )
    _assert_generic_403(resp_payload)


def test_b14a_global_role_behavior_remains_unchanged(store_authz_client):
    client, sf = store_authz_client
    admin_id, _ = _create_staff(sf, email="b14a-admin@example.com", global_role="administrator")
    manager_id, _ = _create_staff(sf, email="b14a-manager@example.com", global_role="manager")

    assert client.get(
        "/protected-admin-b14a-regression", headers=_auth_headers(admin_id)
    ).status_code == 200
    _assert_generic_403(
        client.get("/protected-admin-b14a-regression", headers=_auth_headers(manager_id))
    )
