"""B1.6 Step 2 (batch 6): PostgreSQL-backed HTTP API integration tests for store categories.

Covers (per approved plan and actual endpoint/schema contracts):
- Category list: 200 for authorized Store A member, Store A-only records, schema fields/types,
  accurate totals, deterministic ordering (name asc, id asc per endpoint)
- Pagination: page/page_size behavior, totals scoped with Store B data present, out-of-range page
  returns empty items with accurate total (200), invalid pagination values => 422
- Category detail: existing Store A category 200, nonexistent 404, Store B category via Store A URL 404 (not 403)
- Store isolation and authorization: Store B never in list/totals, nonmember 403, missing/invalid bearer 401
- Response correctness: exact response keys/types/serialization and deterministic assertions

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.core.config import get_settings
from app.models.category import Category

from .helpers_pg import (
    assert_generic_401,
    assert_generic_403,
    assert_generic_404,
    auth_headers,
    auth_headers_for_token,
    create_staff,
    create_store,
    create_store_membership,
)

_TEST_AUTH_ENV = {
    "AUTH_JWT_SECRET": "b16-categories-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.categories.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-categories-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

CATEGORY_ALLOWED_KEYS = {"id", "store_id", "name", "slug", "description", "image", "status", "created_at", "updated_at"}


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


def _list_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/categories"


def _detail_url(store_id: str, category_id: str) -> str:
    return f"/api/v1/stores/{store_id}/categories/{category_id}"


def _create_category(
    sf,
    *,
    store_id: str,
    name: str,
    slug: str,
    status: str = "Active",
    description: str | None = "Desc",
    image: str | None = "https://example.com/cat.png",
) -> str:
    with sf() as db:
        row = Category(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            status=status,
            description=description,
            image=image,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _assert_category_item_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == CATEGORY_ALLOWED_KEYS
    assert item["store_id"] == expected_store_id
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["name"], str)
    assert isinstance(item["slug"], str)
    assert item["description"] is None or isinstance(item["description"], str)
    assert item["image"] is None or isinstance(item["image"], str)
    assert isinstance(item["status"], str)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    # UUID-formatted identifiers in response
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])


def _setup_store_a_member(sf, *, domain: str = "cat-store-a.example.com"):
    user = create_staff(sf, email=f"member-{domain}", global_role="viewer")
    store = create_store(sf, domain=domain, name="Store A", owner="Owner A")
    create_store_membership(sf, store_id=store["id"], staff_user_id=user["id"], role="viewer")
    return user, store


def test_category_list_success_store_scoped_schema_totals_and_deterministic_order(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cat-list-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cat-list-b.example.com", name="Store B", owner="Owner B")

    # Store A categories (ordering per actual endpoint: name asc, id asc; equal-name tie-break required)
    cat_alpha_b = _create_category(pg_api_session_factory, store_id=store_a["id"], name="Alpha", slug="alpha-b", status="Active")
    cat_alpha_a = _create_category(pg_api_session_factory, store_id=store_a["id"], name="Alpha", slug="alpha-a", status="Draft")
    cat_beta = _create_category(pg_api_session_factory, store_id=store_a["id"], name="Beta", slug="beta", status="Active")

    # Store B category must not appear in Store A list/totals
    _create_category(pg_api_session_factory, store_id=store_b["id"], name="Zulu", slug="zulu", status="Active")

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"items", "total", "page", "page_size"}
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 3
    assert len(body["items"]) == 3

    items = body["items"]
    assert [item["name"] for item in items] == ["Alpha", "Alpha", "Beta"]
    alpha_ids = [item["id"] for item in items if item["name"] == "Alpha"]
    assert alpha_ids == sorted([cat_alpha_a, cat_alpha_b])  # id asc tie-breaker
    assert items[2]["id"] == cat_beta

    returned_ids = {item["id"] for item in items}
    assert returned_ids == {cat_alpha_a, cat_alpha_b, cat_beta}
    for item in items:
        _assert_category_item_contract(item, store_a["id"])


def test_category_list_pagination_totals_scoped_and_out_of_range_contract(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cat-page-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cat-page-b.example.com", name="Store B", owner="Owner B")

    # 25 Store A categories
    for i in range(25):
        _create_category(pg_api_session_factory, store_id=store_a["id"], name=f"Cat {i:02d}", slug=f"cat-{i:02d}")
    # Additional Store B categories must not affect Store A totals/pagination
    for i in range(5):
        _create_category(pg_api_session_factory, store_id=store_b["id"], name=f"B Cat {i:02d}", slug=f"b-cat-{i:02d}")

    headers = auth_headers(user_a["id"])

    resp_default = pg_api_client.get(_list_url(store_a["id"]), headers=headers)
    assert resp_default.status_code == 200
    body_default = resp_default.json()
    assert body_default["page"] == 1
    assert body_default["page_size"] == 20
    assert body_default["total"] == 25
    assert len(body_default["items"]) == 20
    assert all(item["store_id"] == store_a["id"] for item in body_default["items"])

    resp_custom = pg_api_client.get(f"{_list_url(store_a['id'])}?page=2&page_size=10", headers=headers)
    assert resp_custom.status_code == 200
    body_custom = resp_custom.json()
    assert body_custom["page"] == 2
    assert body_custom["page_size"] == 10
    assert body_custom["total"] == 25
    assert len(body_custom["items"]) == 10
    assert all(item["store_id"] == store_a["id"] for item in body_custom["items"])

    # Out-of-range page returns 200 with empty items and accurate total (actual contract)
    resp_oor = pg_api_client.get(f"{_list_url(store_a['id'])}?page=5&page_size=20", headers=headers)
    assert resp_oor.status_code == 200
    assert resp_oor.json() == {"items": [], "total": 25, "page": 5, "page_size": 20}


def test_category_list_invalid_pagination_returns_422(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cat-badpage.example.com")
    headers = auth_headers(user_a["id"])

    for qs in ("?page=0", "?page_size=0", "?page_size=101"):
        resp = pg_api_client.get(f"{_list_url(store_a['id'])}{qs}", headers=headers)
        assert resp.status_code == 422, qs


def test_category_detail_success_nonexistent_and_foreign_store_404(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cat-detail-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cat-detail-b.example.com", name="Store B", owner="Owner B")

    cat_a = _create_category(
        pg_api_session_factory,
        store_id=store_a["id"],
        name="Detail Cat",
        slug="detail-cat",
        status="Active",
        description=None,
        image=None,
    )
    cat_b = _create_category(pg_api_session_factory, store_id=store_b["id"], name="Foreign Cat", slug="foreign-cat")

    headers = auth_headers(user_a["id"])

    # Existing Store A category => 200 with exact schema/fields
    resp_ok = pg_api_client.get(_detail_url(store_a["id"], cat_a), headers=headers)
    assert resp_ok.status_code == 200
    body_ok = resp_ok.json()
    assert set(body_ok.keys()) == CATEGORY_ALLOWED_KEYS
    _assert_category_item_contract(body_ok, store_a["id"])
    assert body_ok["id"] == cat_a
    assert body_ok["description"] is None
    assert body_ok["image"] is None

    # Nonexistent category => established 404
    missing_id = str(uuid.uuid4())
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], missing_id), headers=headers))

    # Store B category requested through Store A URL by authorized Store A member => 404 (not 403)
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], cat_b), headers=headers))


def test_category_authorization_store_isolation_and_authentication(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cat-authz-a.example.com")
    user_b = create_staff(pg_api_session_factory, email="member-cat-authz-b.example.com", global_role="viewer")
    store_b = create_store(pg_api_session_factory, domain="cat-authz-b.example.com", name="Store B", owner="Owner B")
    create_store_membership(pg_api_session_factory, store_id=store_b["id"], staff_user_id=user_b["id"], role="owner")

    nonmember = create_staff(pg_api_session_factory, email="nonmember-cat@example.com", global_role="viewer")

    cat_a = _create_category(pg_api_session_factory, store_id=store_a["id"], name="A Cat", slug="a-cat")
    cat_b = _create_category(pg_api_session_factory, store_id=store_b["id"], name="B Cat", slug="b-cat")

    # Store B categories never appear in Store A list results or totals
    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [cat_a]
    assert cat_b not in {item["id"] for item in body["items"]}

    # Authenticated non-member requesting Store A category endpoints => 403
    assert_generic_403(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(nonmember["id"])))
    assert_generic_403(pg_api_client.get(_detail_url(store_a["id"], cat_a), headers=auth_headers(nonmember["id"])))

    # Missing and invalid bearer tokens => generic 401
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"])))
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers_for_token("not-a-jwt")))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], cat_a)))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], cat_a), headers=auth_headers_for_token("not-a-jwt")))
