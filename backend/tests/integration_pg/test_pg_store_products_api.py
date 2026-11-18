"""B1.6 Step 2 (batch 7): PostgreSQL-backed HTTP API integration tests for store products.

Covers (per approved corrected plan and actual endpoint/schema contracts):
- Product list envelope, exact keys/types, UUID/datetime serialization, nullable fields, safe monetary serialization
- Store-scoped list results and accurate totals (Store A never includes Store B products)
- Pagination defaults/custom, invalid params (422), out-of-range (200 empty items + correct total)
- Deterministic ordering including actual tie-breaker (created_at desc, id desc)
- Product detail: existing 200, nonexistent 404, foreign-store product via authorized Store A context 404 (not 403)
- Product images: nested images belong only to requested product/store and match actual schema/ordering
- AuthN/AuthZ: nonmember 403; missing/invalid bearer 401 with existing generic semantics
- PostgreSQL-compatible seed data, FK relationships, fixture-cleanup-compatible setup

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.models.product import Product, ProductImage

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
    "AUTH_JWT_SECRET": "b16-products-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.products.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-products-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

PRODUCT_SUMMARY_KEYS = {
    "id",
    "store_id",
    "name",
    "slug",
    "description",
    "image",
    "category_id",
    "category",
    "price",
    "stock_quantity",
    "low_stock_threshold",
    "sku",
    "status",
    "inventory_updated_at",
    "created_at",
    "updated_at",
}
PRODUCT_DETAIL_KEYS = PRODUCT_SUMMARY_KEYS | {"images"}
PRODUCT_IMAGE_KEYS = {
    "id",
    "product_id",
    "store_id",
    "url",
    "alt",
    "position",
    "created_at",
    "updated_at",
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


def _list_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/products"


def _detail_url(store_id: str, product_id: str) -> str:
    return f"/api/v1/stores/{store_id}/products/{product_id}"


def _setup_store_a_member(sf, *, domain: str = "prod-store-a.example.com", email: str | None = None):
    member_email = email or f"member-{domain}"
    user = create_staff(sf, email=member_email, global_role="viewer")
    store = create_store(sf, domain=domain, name="Store A", owner="Owner A")
    create_store_membership(sf, store_id=store["id"], staff_user_id=user["id"], role="viewer")
    return user, store


def _create_product(
    sf,
    *,
    store_id: str,
    name: str,
    slug: str,
    status: str = "Active",
    price: str = "10.00",
    description: str = "Desc",
    image: str = "https://example.com/main.png",
    category_id: str | None = None,
    category: str | None = None,
    stock_quantity: int = 5,
    low_stock_threshold: int = 1,
    sku: str | None = None,
    inventory_updated_at: datetime | None = None,
) -> str:
    with sf() as db:
        row = Product(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            status=status,
            price=Decimal(price),
            description=description,
            image=image,
            category_id=uuid.UUID(category_id) if category_id else None,
            category=category,
            stock_quantity=stock_quantity,
            low_stock_threshold=low_stock_threshold,
            sku=sku,
            inventory_updated_at=inventory_updated_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_product_image(
    sf,
    *,
    store_id: str,
    product_id: str,
    url: str,
    position: int,
    alt: str | None = None,
) -> str:
    with sf() as db:
        row = ProductImage(
            store_id=uuid.UUID(store_id),
            product_id=uuid.UUID(product_id),
            url=url,
            position=position,
            alt=alt,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _set_product_created_at(sf, product_id: str, created_at: datetime) -> None:
    with sf() as db:
        row = db.get(Product, uuid.UUID(product_id))
        assert row is not None
        row.created_at = created_at
        db.commit()


def _assert_product_summary_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == PRODUCT_SUMMARY_KEYS
    assert item["store_id"] == expected_store_id
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["name"], str)
    assert isinstance(item["slug"], str)
    assert isinstance(item["description"], str)
    assert isinstance(item["image"], str)
    assert item["category_id"] is None or isinstance(item["category_id"], str)
    assert item["category"] is None or isinstance(item["category"], str)
    assert isinstance(item["price"], str)
    assert isinstance(item["stock_quantity"], int)
    assert isinstance(item["low_stock_threshold"], int)
    assert item["sku"] is None or isinstance(item["sku"], str)
    assert isinstance(item["status"], str)
    assert item["inventory_updated_at"] is None or isinstance(item["inventory_updated_at"], str)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    if item["category_id"] is not None:
        uuid.UUID(item["category_id"])


def _assert_product_image_contract(img: dict, expected_store_id: str, expected_product_id: str) -> None:
    assert set(img.keys()) == PRODUCT_IMAGE_KEYS
    assert img["store_id"] == expected_store_id
    assert img["product_id"] == expected_product_id
    assert isinstance(img["id"], str) and img["id"]
    assert isinstance(img["url"], str) and img["url"]
    assert img["alt"] is None or isinstance(img["alt"], str)
    assert isinstance(img["position"], int)
    assert isinstance(img["created_at"], str) and img["created_at"]
    assert isinstance(img["updated_at"], str) and img["updated_at"]
    uuid.UUID(img["id"])
    uuid.UUID(img["product_id"])
    uuid.UUID(img["store_id"])


def test_product_list_success_scoped_schema_nullable_and_monetary_serialization(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="prod-list-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="prod-list-b.example.com", name="Store B", owner="Owner B")

    prod_a = _create_product(
        pg_api_session_factory,
        store_id=store_a["id"],
        name="Alpha Product",
        slug="alpha-product",
        status="Active",
        price="12.30",
        description="Alpha desc",
        image="https://example.com/alpha.png",
        category_id=None,
        category=None,
        stock_quantity=7,
        low_stock_threshold=2,
        sku=None,
        inventory_updated_at=None,
    )
    prod_b = _create_product(pg_api_session_factory, store_id=store_b["id"], name="B Product", slug="b-product", price="99.99")

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"items", "total", "page", "page_size"}
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]
    _assert_product_summary_contract(item, store_a["id"])
    assert item["id"] == prod_a
    assert item["name"] == "Alpha Product"
    assert item["slug"] == "alpha-product"
    assert item["category_id"] is None
    assert item["category"] is None
    assert item["sku"] is None
    assert item["inventory_updated_at"] is None
    assert item["price"] == "12.30"
    assert isinstance(item["price"], str)
    assert '"price":"12.30"' in resp.text or '"price": "12.30"' in resp.text

    returned_ids = {it["id"] for it in body["items"]}
    assert prod_b not in returned_ids
    assert all(it["store_id"] == store_a["id"] for it in body["items"])


def test_product_list_pagination_defaults_custom_invalid_and_out_of_range(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="prod-page-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="prod-page-b.example.com", name="Store B", owner="Owner B")

    for i in range(25):
        _create_product(pg_api_session_factory, store_id=store_a["id"], name=f"Prod {i:02d}", slug=f"prod-{i:02d}")
    for i in range(5):
        _create_product(pg_api_session_factory, store_id=store_b["id"], name=f"B Prod {i:02d}", slug=f"b-prod-{i:02d}")

    headers = auth_headers(user_a["id"])

    resp_default = pg_api_client.get(_list_url(store_a["id"]), headers=headers)
    assert resp_default.status_code == 200
    body_default = resp_default.json()
    assert body_default["page"] == 1
    assert body_default["page_size"] == 20
    assert body_default["total"] == 25
    assert len(body_default["items"]) == 20
    assert all(it["store_id"] == store_a["id"] for it in body_default["items"])

    resp_custom = pg_api_client.get(f"{_list_url(store_a['id'])}?page=2&page_size=10", headers=headers)
    assert resp_custom.status_code == 200
    body_custom = resp_custom.json()
    assert body_custom["page"] == 2
    assert body_custom["page_size"] == 10
    assert body_custom["total"] == 25
    assert len(body_custom["items"]) == 10
    assert all(it["store_id"] == store_a["id"] for it in body_custom["items"])

    resp_oor = pg_api_client.get(f"{_list_url(store_a['id'])}?page=5&page_size=20", headers=headers)
    assert resp_oor.status_code == 200
    assert resp_oor.json() == {"items": [], "total": 25, "page": 5, "page_size": 20}

    for qs in ("?page=0", "?page_size=0", "?page_size=101"):
        resp_invalid = pg_api_client.get(f"{_list_url(store_a['id'])}{qs}", headers=headers)
        assert resp_invalid.status_code == 422, qs


def test_product_list_deterministic_ordering_created_at_desc_then_id_desc(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="prod-order.example.com")

    p1 = _create_product(pg_api_session_factory, store_id=store_a["id"], name="P1", slug="p1")
    p2 = _create_product(pg_api_session_factory, store_id=store_a["id"], name="P2", slug="p2")
    p3 = _create_product(pg_api_session_factory, store_id=store_a["id"], name="P3", slug="p3")

    older = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)
    _set_product_created_at(pg_api_session_factory, p1, older)
    _set_product_created_at(pg_api_session_factory, p2, newer)
    _set_product_created_at(pg_api_session_factory, p3, newer)  # tie on created_at -> id DESC

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids.index(p1) == 2
    assert set(ids[:2]) == {p2, p3}
    assert ids[0] > ids[1]  # actual tie-breaker: id DESC within equal created_at group


def test_product_detail_existing_nonexistent_and_foreign_store_404(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="prod-detail-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="prod-detail-b.example.com", name="Store B", owner="Owner B")

    prod_a = _create_product(
        pg_api_session_factory,
        store_id=store_a["id"],
        name="Detail Product",
        slug="detail-product",
        status="Draft",
        price="7.50",
        description="Detail desc",
        image="https://example.com/detail.png",
        category_id=None,
        category=None,
        stock_quantity=3,
        low_stock_threshold=0,
        sku="SKU-DETAIL-1",
        inventory_updated_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    prod_b = _create_product(pg_api_session_factory, store_id=store_b["id"], name="Foreign Product", slug="foreign-product")

    headers = auth_headers(user_a["id"])

    resp_ok = pg_api_client.get(_detail_url(store_a["id"], prod_a), headers=headers)
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert set(body.keys()) == PRODUCT_DETAIL_KEYS
    _assert_product_summary_contract({k: v for k, v in body.items() if k != "images"}, store_a["id"])
    assert body["id"] == prod_a
    assert body["status"] == "Draft"
    assert body["price"] == "7.50"
    assert isinstance(body["price"], str)
    assert body["sku"] == "SKU-DETAIL-1"
    assert body["category_id"] is None
    assert body["category"] is None
    assert isinstance(body["inventory_updated_at"], str) and body["inventory_updated_at"]
    assert body["images"] == []

    missing_id = str(uuid.uuid4())
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], missing_id), headers=headers))

    # Foreign-store product requested through authorized Store A context => 404 (not 403)
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], prod_b), headers=headers))


def test_product_detail_images_scoped_schema_and_ordering(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="prod-images-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="prod-images-b.example.com", name="Store B", owner="Owner B")

    prod_a1 = _create_product(pg_api_session_factory, store_id=store_a["id"], name="A1", slug="a1")
    prod_a2 = _create_product(pg_api_session_factory, store_id=store_a["id"], name="A2", slug="a2")
    prod_b1 = _create_product(pg_api_session_factory, store_id=store_b["id"], name="B1", slug="b1")

    # Positions unique per (store,product,position); verify actual ordering position ASC, id ASC.
    img3 = _create_product_image(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a1, url="https://example.com/3.png", position=3, alt="c"
    )
    img1 = _create_product_image(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a1, url="https://example.com/1.png", position=1, alt="a"
    )
    img2 = _create_product_image(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a1, url="https://example.com/2.png", position=2, alt="b"
    )
    # Images on another product in same store and in other store must not leak.
    _create_product_image(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a2, url="https://example.com/a2.png", position=1, alt=None
    )
    _create_product_image(
        pg_api_session_factory, store_id=store_b["id"], product_id=prod_b1, url="https://example.com/b1.png", position=1, alt=None
    )

    resp = pg_api_client.get(_detail_url(store_a["id"], prod_a1), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == PRODUCT_DETAIL_KEYS

    images = body["images"]
    assert [im["id"] for im in images] == [img1, img2, img3]
    assert [im["position"] for im in images] == [1, 2, 3]
    for im in images:
        _assert_product_image_contract(im, store_a["id"], prod_a1)
    assert {im["id"] for im in images} == {img1, img2, img3}


def test_product_authorization_and_authentication(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="prod-authz-a.example.com")
    nonmember = create_staff(pg_api_session_factory, email="nonmember-prod-authz@example.com", global_role="viewer")

    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], name="Authz Product", slug="authz-product")

    # Authorized member can read list/detail
    ok_list = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert ok_list.status_code == 200
    assert ok_list.json()["total"] == 1
    ok_detail = pg_api_client.get(_detail_url(store_a["id"], prod_a), headers=auth_headers(user_a["id"]))
    assert ok_detail.status_code == 200

    # Authenticated non-member => 403 (generic)
    assert_generic_403(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(nonmember["id"])))
    assert_generic_403(pg_api_client.get(_detail_url(store_a["id"], prod_a), headers=auth_headers(nonmember["id"])))

    # Missing and invalid bearer tokens => generic 401
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"])))
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers_for_token("not-a-jwt")))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], prod_a)))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], prod_a), headers=auth_headers_for_token("not-a-jwt")))
