"""B2 Batch 3: PostgreSQL-backed HTTP API integration tests for storefront hero admin endpoints.

Covers (approved B2 Batch 3 scope):
- GET  /stores/{store_id}/storefront/hero
  - AuthZ: owner/manager/viewer 200; authenticated non-member 403;
    platform admin without membership 403 (no bypass); missing/invalid bearer 401;
    inactive staff 401 (applicable auth failure).
  - Pagination envelope and visibility of disabled/ineligible mappings.
- PUT  /stores/{store_id}/storefront/hero/order
  - Owner/manager success with complete ordering (incl. disabled/ineligible).
  - Duplicate, missing, unknown, and foreign-store category rejection (422).
  - Viewer write denial (403).
- PATCH /stores/{store_id}/storefront/hero/categories/{category_id}
  - Omitted-field behavior unchanged.
  - Explicit null semantics: admin_is_enabled null => 422, featured_product_id null clears.
  - Valid featured-product selection and clearing.
  - Invalid, inactive, cross-category, cross-store featured-product rejection (422).
  - Missing mapping => 404.
- POST /stores/{store_id}/storefront/hero/sync
  - Idempotency and preservation of existing mapping IDs/positions/order intent/
    enablement/featured selections and legacy/unmapped rows.
- Cross-store isolation.
- Existing GET /stores/{store_id}/storefront/slides compatibility preserved.

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.category import Category
from app.models.product import Product
from app.models.storefront import StorefrontSlide

from .helpers_pg import (
    assert_generic_401,
    assert_generic_403,
    auth_headers,
    auth_headers_for_token,
    create_staff,
    create_store,
    create_store_membership,
)

_TEST_AUTH_ENV = {
    "AUTH_JWT_SECRET": "b2-hero-api-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b2.hero.api.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b2-hero-api-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

HERO_ENVELOPE_KEYS = {"items", "total", "page", "page_size"}
HERO_ITEM_KEYS = {
    "id",
    "store_id",
    "category_id",
    "position",
    "admin_is_enabled",
    "is_active",
    "featured_product_id",
    "eligibility",
    "manual_featured_product_valid",
    "effective_featured_product",
    "featured_resolution_source",
    "title",
    "subtitle",
    "image_url",
    "cta_url",
    "cta_label",
    "target_category_id",
    "created_at",
    "updated_at",
}
ELIGIBILITY_KEYS = {"category_active", "has_eligible_active_product", "is_publicly_eligible"}
EFFECTIVE_PRODUCT_KEYS = {"id", "store_id", "category_id", "name", "slug", "image", "status"}
SLIDE_KEYS = {
    "id",
    "store_id",
    "title",
    "subtitle",
    "image_url",
    "cta_url",
    "cta_label",
    "position",
    "target_category_id",
    "is_active",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _b2_auth_env():
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


def _hero_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/hero"


def _hero_order_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/hero/order"


def _hero_patch_url(store_id: str, category_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/hero/categories/{category_id}"


def _hero_sync_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/hero/sync"


def _slides_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/slides"


def _create_category(
    sf,
    *,
    store_id: str,
    name: str,
    slug: str,
    status: str = "Active",
) -> str:
    with sf() as db:
        row = Category(store_id=uuid.UUID(store_id), name=name, slug=slug, status=status)
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_product(
    sf,
    *,
    store_id: str,
    category_id: str | None,
    name: str,
    slug: str,
    status: str = "Active",
    image: str = "https://example.com/p.png",
    stock_quantity: int = 10,
) -> str:
    with sf() as db:
        row = Product(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            description="",
            image=image or "",
            price=10.00,
            stock_quantity=stock_quantity,
            low_stock_threshold=0,
            sku=None,
            status=status,
            category=name if category_id is None else "",  # display cache best-effort
            category_id=uuid.UUID(category_id) if category_id else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_mapped_slide(
    sf,
    *,
    store_id: str,
    category_id: str,
    position: int,
    title: str = "Hero",
    featured_product_id: str | None = None,
    admin_is_enabled: bool = True,
    is_active: bool = True,
    image_url: str = "https://example.com/hero.png",
) -> str:
    with sf() as db:
        row = StorefrontSlide(
            store_id=uuid.UUID(store_id),
            title=title,
            subtitle=None,
            image_url=image_url,
            cta_url=None,
            cta_label=None,
            position=position,
            target_category_id=uuid.UUID(category_id),
            is_active=is_active,
            category_id=uuid.UUID(category_id),
            featured_product_id=uuid.UUID(featured_product_id) if featured_product_id else None,
            admin_is_enabled=admin_is_enabled,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_unmapped_legacy_slide(
    sf,
    *,
    store_id: str,
    position: int,
    title: str = "Legacy",
) -> str:
    with sf() as db:
        row = StorefrontSlide(
            store_id=uuid.UUID(store_id),
            title=title,
            subtitle="legacy-sub",
            image_url="https://example.com/legacy.png",
            cta_url="https://example.com/legacy-cta",
            cta_label="Legacy CTA",
            position=position,
            target_category_id=None,
            is_active=True,
            category_id=None,
            featured_product_id=None,
            admin_is_enabled=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _get_slide(sf, slide_id: str) -> dict[str, Any]:
    with sf() as db:
        row = db.get(StorefrontSlide, uuid.UUID(slide_id))
        assert row is not None
        return {
            "id": str(row.id),
            "store_id": str(row.store_id),
            "category_id": str(row.category_id) if row.category_id else None,
            "position": row.position,
            "featured_product_id": str(row.featured_product_id) if row.featured_product_id else None,
            "admin_is_enabled": row.admin_is_enabled,
            "is_active": row.is_active,
            "title": row.title,
        }


def _assert_hero_item_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == HERO_ITEM_KEYS
    assert item["store_id"] == expected_store_id
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    uuid.UUID(item["category_id"])
    assert isinstance(item["position"], int) and item["position"] >= 1
    assert isinstance(item["admin_is_enabled"], bool)
    assert isinstance(item["is_active"], bool)
    if item["featured_product_id"] is None:
        assert item["featured_product_id"] is None
    else:
        uuid.UUID(item["featured_product_id"])
    assert set(item["eligibility"].keys()) == ELIGIBILITY_KEYS
    for k in ELIGIBILITY_KEYS:
        assert isinstance(item["eligibility"][k], bool)
    assert isinstance(item["manual_featured_product_valid"], bool)
    assert item["featured_resolution_source"] in {"manual", "fallback", "none"}
    if item["effective_featured_product"] is None:
        assert item["featured_resolution_source"] == "none" or item["featured_resolution_source"] in {"manual", "fallback"}
    else:
        assert set(item["effective_featured_product"].keys()) == EFFECTIVE_PRODUCT_KEYS
        uuid.UUID(item["effective_featured_product"]["id"])
        assert item["effective_featured_product"]["store_id"] == expected_store_id
    assert isinstance(item["title"], str)
    assert item["subtitle"] is None or isinstance(item["subtitle"], str)
    assert isinstance(item["image_url"], str)
    assert item["cta_url"] is None or isinstance(item["cta_url"], str)
    assert item["cta_label"] is None or isinstance(item["cta_label"], str)
    if item["target_category_id"] is not None:
        uuid.UUID(item["target_category_id"])
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]


def test_get_hero_authz_owner_manager_viewer_and_denials(pg_api_client, pg_api_session_factory):
    store = create_store(pg_api_session_factory, domain="hero-authz.example.com", name="Hero Store", owner="Owner")
    cat = _create_category(pg_api_session_factory, store_id=store["id"], name="Cat", slug="cat")
    _create_product(pg_api_session_factory, store_id=store["id"], category_id=cat, name="Prod", slug="prod")
    _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=cat, position=1, title="Cat")

    owner = create_staff(pg_api_session_factory, email="hero-owner@example.com", global_role="viewer")
    manager = create_staff(pg_api_session_factory, email="hero-manager@example.com", global_role="viewer")
    viewer = create_staff(pg_api_session_factory, email="hero-viewer@example.com", global_role="viewer")
    nonmember = create_staff(pg_api_session_factory, email="hero-nonmember@example.com", global_role="viewer")
    platform_admin = create_staff(pg_api_session_factory, email="hero-admin@example.com", global_role="administrator")
    inactive = create_staff(pg_api_session_factory, email="hero-inactive@example.com", global_role="viewer", status="Inactive")

    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=owner["id"], role="owner")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=manager["id"], role="manager")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=viewer["id"], role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=inactive["id"], role="viewer")

    url = _hero_url(store["id"])

    # Authorized store members (owner/manager/viewer) can read
    for user in (owner, manager, viewer):
        resp = pg_api_client.get(url, headers=auth_headers(user["id"]))
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == HERO_ENVELOPE_KEYS
        assert body["total"] == 1
        assert len(body["items"]) == 1
        _assert_hero_item_contract(body["items"][0], store["id"])

    # Authenticated non-member => 403
    assert_generic_403(pg_api_client.get(url, headers=auth_headers(nonmember["id"])))
    # Platform administrator without store membership => 403 (no bypass)
    assert_generic_403(pg_api_client.get(url, headers=auth_headers(platform_admin["id"])))
    # Missing / invalid bearer => 401
    assert_generic_401(pg_api_client.get(url))
    assert_generic_401(pg_api_client.get(url, headers=auth_headers_for_token("not-a-jwt")))
    # Inactive staff (valid token, but inactive user) => 401
    assert_generic_401(pg_api_client.get(url, headers=auth_headers(inactive["id"])))


def test_get_hero_pagination_and_visibility_of_disabled_ineligible_mappings(pg_api_client, pg_api_session_factory):
    user = create_staff(pg_api_session_factory, email="hero-page@example.com", global_role="viewer")
    store = create_store(pg_api_session_factory, domain="hero-page.example.com", name="Hero Page", owner="Owner")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=user["id"], role="viewer")

    active_cat = _create_category(pg_api_session_factory, store_id=store["id"], name="Active", slug="active", status="Active")
    _create_product(pg_api_session_factory, store_id=store["id"], category_id=active_cat, name="AProd", slug="aprod", status="Active")
    draft_cat = _create_category(pg_api_session_factory, store_id=store["id"], name="Draft", slug="draft", status="Draft")
    _create_product(pg_api_session_factory, store_id=store["id"], category_id=draft_cat, name="DProd", slug="dprod", status="Active")

    s1 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=active_cat, position=1, admin_is_enabled=True)
    s2 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=draft_cat, position=2, admin_is_enabled=False)

    headers = auth_headers(user["id"])
    resp = pg_api_client.get(f"{_hero_url(store['id'])}?page=1&page_size=1", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {**body, "items": body["items"], "total": 2, "page": 1, "page_size": 1}
    assert set(body.keys()) == HERO_ENVELOPE_KEYS
    assert body["total"] == 2
    assert body["page"] == 1 and body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == s1

    resp2 = pg_api_client.get(f"{_hero_url(store['id'])}?page=2&page_size=1", headers=headers)
    assert resp2.status_code == 200
    b2 = resp2.json()
    assert b2["total"] == 2 and b2["page"] == 2 and len(b2["items"]) == 1
    assert b2["items"][0]["id"] == s2
    assert b2["items"][0]["admin_is_enabled"] is False  # disabled present
    assert b2["items"][0]["eligibility"]["category_active"] is False
    assert b2["items"][0]["eligibility"]["is_publicly_eligible"] is False  # ineligible present

    # out-of-range
    resp_oor = pg_api_client.get(f"{_hero_url(store['id'])}?page=5&page_size=1", headers=headers)
    assert resp_oor.status_code == 200
    assert resp_oor.json() == {"items": [], "total": 2, "page": 5, "page_size": 1}

    # invalid pagination
    assert pg_api_client.get(f"{_hero_url(store['id'])}?page=0", headers=headers).status_code == 422


def test_put_order_success_complete_including_disabled_ineligible_and_viewer_denied(pg_api_client, pg_api_session_factory):
    store = create_store(pg_api_session_factory, domain="hero-order.example.com", name="Order Store", owner="Owner")
    owner = create_staff(pg_api_session_factory, email="order-owner@example.com", global_role="viewer")
    viewer = create_staff(pg_api_session_factory, email="order-viewer@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=owner["id"], role="owner")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=viewer["id"], role="viewer")

    c1 = _create_category(pg_api_session_factory, store_id=store["id"], name="C1", slug="c1", status="Active")
    c2 = _create_category(pg_api_session_factory, store_id=store["id"], name="C2", slug="c2", status="Draft")  # ineligible
    c3 = _create_category(pg_api_session_factory, store_id=store["id"], name="C3", slug="c3", status="Active")
    _create_product(pg_api_session_factory, store_id=store["id"], category_id=c1, name="P1", slug="p1")
    _create_product(pg_api_session_factory, store_id=store["id"], category_id=c3, name="P3", slug="p3")

    s1 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=c1, position=1, admin_is_enabled=True)
    s2 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=c2, position=2, admin_is_enabled=False)
    s3 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=c3, position=3, admin_is_enabled=True)

    url = _hero_order_url(store["id"])
    new_order = [c3, c1, c2]  # complete, includes disabled/ineligible

    # viewer denied
    assert_generic_403(pg_api_client.put(url, headers=auth_headers(viewer["id"]), json={"category_ids": new_order}))

    resp = pg_api_client.put(url, headers=auth_headers(owner["id"]), json={"category_ids": new_order})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == HERO_ENVELOPE_KEYS
    assert body["total"] == 3
    assert [i["category_id"] for i in body["items"]] == new_order
    assert [i["position"] for i in body["items"]] == [1, 2, 3]
    assert [i["id"] for i in body["items"]] == [s3, s1, s2]
    assert [i["admin_is_enabled"] for i in body["items"]] == [True, True, False]

    # persisted
    assert _get_slide(pg_api_session_factory, s3)["position"] == 1
    assert _get_slide(pg_api_session_factory, s1)["position"] == 2
    assert _get_slide(pg_api_session_factory, s2)["position"] == 3


def test_put_order_rejects_duplicate_missing_unknown_foreign_store(pg_api_client, pg_api_session_factory):
    store_a = create_store(pg_api_session_factory, domain="hero-order-a.example.com", name="A", owner="A")
    store_b = create_store(pg_api_session_factory, domain="hero-order-b.example.com", name="B", owner="B")
    owner_a = create_staff(pg_api_session_factory, email="order-a@example.com", global_role="viewer")
    owner_b = create_staff(pg_api_session_factory, email="order-b@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store_a["id"], staff_user_id=owner_a["id"], role="owner")
    create_store_membership(pg_api_session_factory, store_id=store_b["id"], staff_user_id=owner_b["id"], role="owner")

    a1 = _create_category(pg_api_session_factory, store_id=store_a["id"], name="A1", slug="a1")
    a2 = _create_category(pg_api_session_factory, store_id=store_a["id"], name="A2", slug="a2")
    b1 = _create_category(pg_api_session_factory, store_id=store_b["id"], name="B1", slug="b1")
    _create_mapped_slide(pg_api_session_factory, store_id=store_a["id"], category_id=a1, position=1)
    _create_mapped_slide(pg_api_session_factory, store_id=store_a["id"], category_id=a2, position=2)
    _create_mapped_slide(pg_api_session_factory, store_id=store_b["id"], category_id=b1, position=1)

    url_a = _hero_order_url(store_a["id"])
    headers_a = auth_headers(owner_a["id"])

    # duplicate
    r_dup = pg_api_client.put(url_a, headers=headers_a, json={"category_ids": [a1, a1]})
    assert r_dup.status_code == 422
    # missing (not all mapped included)
    r_missing = pg_api_client.put(url_a, headers=headers_a, json={"category_ids": [a1]})
    assert r_missing.status_code == 422
    # unknown (not a mapped category in this store)
    r_unknown = pg_api_client.put(url_a, headers=headers_a, json={"category_ids": [a1, str(uuid.uuid4())]})
    assert r_unknown.status_code == 422
    # foreign-store category id
    r_foreign = pg_api_client.put(url_a, headers=headers_a, json={"category_ids": [a1, b1]})
    assert r_foreign.status_code == 422

    # order unchanged
    get_resp = pg_api_client.get(_hero_url(store_a["id"]), headers=headers_a)
    assert [i["category_id"] for i in get_resp.json()["items"]] == [a1, a2]


def test_patch_omitted_fields_null_semantics_valid_selection_clearing_and_rejections(pg_api_client, pg_api_session_factory):
    store = create_store(pg_api_session_factory, domain="hero-patch.example.com", name="Patch", owner="Owner")
    owner = create_staff(pg_api_session_factory, email="patch-owner@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=owner["id"], role="owner")
    headers = auth_headers(owner["id"])

    cat = _create_category(pg_api_session_factory, store_id=store["id"], name="Cat", slug="cat", status="Active")
    cat2 = _create_category(pg_api_session_factory, store_id=store["id"], name="Cat2", slug="cat2", status="Active")
    p_valid = _create_product(pg_api_session_factory, store_id=store["id"], category_id=cat, name="Valid", slug="valid", status="Active")
    p_inactive = _create_product(pg_api_session_factory, store_id=store["id"], category_id=cat, name="Draft", slug="draft", status="Draft")
    p_cross_cat = _create_product(pg_api_session_factory, store_id=store["id"], category_id=cat2, name="Other", slug="other", status="Active")

    store_b = create_store(pg_api_session_factory, domain="hero-patch-b.example.com", name="B", owner="B")
    cat_b = _create_category(pg_api_session_factory, store_id=store_b["id"], name="BCat", slug="bcat", status="Active")
    p_cross_store = _create_product(pg_api_session_factory, store_id=store_b["id"], category_id=cat_b, name="BProd", slug="bprod", status="Active")

    slide_id = _create_mapped_slide(
        pg_api_session_factory,
        store_id=store["id"],
        category_id=cat,
        position=1,
        admin_is_enabled=True,
        featured_product_id=p_valid,
    )
    url = _hero_patch_url(store["id"], cat)

    # Omitted fields unchanged (empty payload / no-op)
    before = _get_slide(pg_api_session_factory, slide_id)
    resp_noop = pg_api_client.patch(url, headers=headers, json={})
    assert resp_noop.status_code == 200
    item = resp_noop.json()
    assert item["admin_is_enabled"] == before["admin_is_enabled"]
    assert item["featured_product_id"] == before["featured_product_id"]

    # Omitted admin_is_enabled unchanged when clearing featured
    resp_clear = pg_api_client.patch(url, headers=headers, json={"featured_product_id": None})
    assert resp_clear.status_code == 200
    assert resp_clear.json()["admin_is_enabled"] is True
    assert resp_clear.json()["featured_product_id"] is None
    assert _get_slide(pg_api_session_factory, slide_id)["featured_product_id"] is None

    # Valid featured-product selection
    resp_set = pg_api_client.patch(url, headers=headers, json={"featured_product_id": p_valid})
    assert resp_set.status_code == 200
    assert resp_set.json()["featured_product_id"] == p_valid
    assert resp_set.json()["manual_featured_product_valid"] is True
    assert resp_set.json()["featured_resolution_source"] == "manual"

    # Omitted featured_product_id unchanged when toggling admin flag
    resp_toggle = pg_api_client.patch(url, headers=headers, json={"admin_is_enabled": False})
    assert resp_toggle.status_code == 200
    assert resp_toggle.json()["admin_is_enabled"] is False
    assert resp_toggle.json()["featured_product_id"] == p_valid
    assert _get_slide(pg_api_session_factory, slide_id)["admin_is_enabled"] is False
    assert _get_slide(pg_api_session_factory, slide_id)["featured_product_id"] == p_valid

    # Explicit null for admin_is_enabled => 422
    resp_admin_null = pg_api_client.patch(url, headers=headers, json={"admin_is_enabled": None})
    assert resp_admin_null.status_code == 422

    # Invalid/inactive/cross-category/cross-store featured-product rejection => 422
    for bad_pid in (p_inactive, p_cross_cat, p_cross_store, str(uuid.uuid4())):
        r = pg_api_client.patch(url, headers=headers, json={"featured_product_id": bad_pid})
        assert r.status_code == 422, bad_pid
    # state preserved after rejections
    after = _get_slide(pg_api_session_factory, slide_id)
    assert after["admin_is_enabled"] is False
    assert after["featured_product_id"] == p_valid

    # Viewer write denial
    viewer = create_staff(pg_api_session_factory, email="patch-viewer@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=viewer["id"], role="viewer")
    assert_generic_403(pg_api_client.patch(url, headers=auth_headers(viewer["id"]), json={"admin_is_enabled": True}))


def test_patch_missing_mapping_returns_404(pg_api_client, pg_api_session_factory):
    store = create_store(pg_api_session_factory, domain="hero-missing.example.com", name="Missing", owner="Owner")
    owner = create_staff(pg_api_session_factory, email="missing-owner@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=owner["id"], role="owner")
    cat = _create_category(pg_api_session_factory, store_id=store["id"], name="Cat", slug="cat")
    # no mapping created for category
    resp = pg_api_client.patch(
        _hero_patch_url(store["id"], cat),
        headers=auth_headers(owner["id"]),
        json={"admin_is_enabled": False},
    )
    assert resp.status_code == 404


def test_post_sync_idempotent_preserves_intent_and_legacy_unmapped_rows(pg_api_client, pg_api_session_factory):
    store = create_store(pg_api_session_factory, domain="hero-sync.example.com", name="Sync", owner="Owner")
    owner = create_staff(pg_api_session_factory, email="sync-owner@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=owner["id"], role="owner")
    headers = auth_headers(owner["id"])

    c1 = _create_category(pg_api_session_factory, store_id=store["id"], name="C1", slug="c1")
    c2 = _create_category(pg_api_session_factory, store_id=store["id"], name="C2", slug="c2")
    c3 = _create_category(pg_api_session_factory, store_id=store["id"], name="C3", slug="c3")  # will be missing initially
    p1 = _create_product(pg_api_session_factory, store_id=store["id"], category_id=c1, name="P1", slug="p1", status="Active")

    s1 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=c1, position=2, admin_is_enabled=False, featured_product_id=p1)
    s2 = _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=c2, position=1, admin_is_enabled=True, featured_product_id=None)
    legacy_id = _create_unmapped_legacy_slide(pg_api_session_factory, store_id=store["id"], position=10, title="Legacy Unmapped")

    url = _hero_sync_url(store["id"])
    resp1 = pg_api_client.post(url, headers=headers)
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert set(body1.keys()) == HERO_ENVELOPE_KEYS
    assert body1["total"] == 3  # all store categories mapped
    items1 = body1["items"]
    by_cat = {i["category_id"]: i for i in items1}
    assert set(by_cat.keys()) == {c1, c2, c3}
    # existing mapping IDs and intent preserved
    assert by_cat[c1]["id"] == s1 and by_cat[c1]["admin_is_enabled"] is False and by_cat[c1]["featured_product_id"] == p1
    assert by_cat[c2]["id"] == s2 and by_cat[c2]["admin_is_enabled"] is True and by_cat[c2]["featured_product_id"] is None
    # existing mapped rows preserve their relative order; new mapping appended
    assert [i["category_id"] for i in items1] == [c2, c1, c3]
    assert [i["position"] for i in items1] == [1, 2, 3]
    assert by_cat[c3]["featured_product_id"] is None and by_cat[c3]["admin_is_enabled"] is True
    new_s3_id = by_cat[c3]["id"]

    # legacy/unmapped row preserved
    legacy_after = _get_slide(pg_api_session_factory, legacy_id)
    assert legacy_after["category_id"] is None
    assert legacy_after["title"] == "Legacy Unmapped"

    # idempotent
    resp2 = pg_api_client.post(url, headers=headers)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["total"] == 3
    by_cat2 = {i["category_id"]: i for i in body2["items"]}
    assert by_cat2[c1]["id"] == s1 and by_cat2[c2]["id"] == s2 and by_cat2[c3]["id"] == new_s3_id
    assert [i["category_id"] for i in body2["items"]] == [c2, c1, c3]
    assert [i["position"] for i in body2["items"]] == [1, 2, 3]
    assert by_cat2[c1]["admin_is_enabled"] is False and by_cat2[c1]["featured_product_id"] == p1
    assert _get_slide(pg_api_session_factory, legacy_id)["category_id"] is None


def test_cross_store_isolation_and_foreign_store_behavior(pg_api_client, pg_api_session_factory):
    store_a = create_store(pg_api_session_factory, domain="hero-iso-a.example.com", name="A", owner="A")
    store_b = create_store(pg_api_session_factory, domain="hero-iso-b.example.com", name="B", owner="B")
    user_a = create_staff(pg_api_session_factory, email="iso-a@example.com", global_role="viewer")
    user_b = create_staff(pg_api_session_factory, email="iso-b@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store_a["id"], staff_user_id=user_a["id"], role="owner")
    create_store_membership(pg_api_session_factory, store_id=store_b["id"], staff_user_id=user_b["id"], role="owner")

    cat_a = _create_category(pg_api_session_factory, store_id=store_a["id"], name="Acat", slug="acat")
    cat_b = _create_category(pg_api_session_factory, store_id=store_b["id"], name="Bcat", slug="bcat")
    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], category_id=cat_a, name="Aprod", slug="aprod")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b["id"], category_id=cat_b, name="Bprod", slug="bprod")
    sa = _create_mapped_slide(pg_api_session_factory, store_id=store_a["id"], category_id=cat_a, position=1)
    sb = _create_mapped_slide(pg_api_session_factory, store_id=store_b["id"], category_id=cat_b, position=1)

    headers_a = auth_headers(user_a["id"])

    # GET isolation
    resp = pg_api_client.get(_hero_url(store_a["id"]), headers=headers_a)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == sa
    assert body["items"][0]["store_id"] == store_a["id"]
    assert sb not in [i["id"] for i in body["items"]]

    # Non-member of store B cannot access store B hero endpoints (403, generic)
    assert_generic_403(pg_api_client.get(_hero_url(store_b["id"]), headers=headers_a))
    assert_generic_403(pg_api_client.put(_hero_order_url(store_b["id"]), headers=headers_a, json={"category_ids": [cat_b]}))
    assert_generic_403(pg_api_client.patch(_hero_patch_url(store_b["id"], cat_b), headers=headers_a, json={"admin_is_enabled": False}))
    assert_generic_403(pg_api_client.post(_hero_sync_url(store_b["id"]), headers=headers_a))

    # Authorized to store A: foreign-store category references must not mutate/leak store B
    before_b = _get_slide(pg_api_session_factory, sb)
    # PATCH against store A with store B category -> 404 in store A scope (no existence leak of B resource)
    assert pg_api_client.patch(_hero_patch_url(store_a["id"], cat_b), headers=headers_a, json={"admin_is_enabled": False}).status_code == 404
    # PUT order including foreign-store category -> 422
    assert pg_api_client.put(_hero_order_url(store_a["id"]), headers=headers_a, json={"category_ids": [cat_b]}).status_code == 422
    # PATCH featured selection to foreign-store/cross-store product -> 422
    assert pg_api_client.patch(_hero_patch_url(store_a["id"], cat_a), headers=headers_a, json={"featured_product_id": prod_b}).status_code == 422
    assert _get_slide(pg_api_session_factory, sb) == before_b
    assert _get_slide(pg_api_session_factory, sa)["store_id"] == store_a["id"]


def test_existing_slides_endpoint_compatibility_preserved(pg_api_client, pg_api_session_factory):
    user = create_staff(pg_api_session_factory, email="slides-compat@example.com", global_role="viewer")
    store = create_store(pg_api_session_factory, domain="slides-compat.example.com", name="Slides Compat", owner="Owner")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=user["id"], role="viewer")

    cat = _create_category(pg_api_session_factory, store_id=store["id"], name="Cat", slug="cat")
    _create_mapped_slide(pg_api_session_factory, store_id=store["id"], category_id=cat, position=1, title="Mapped Hero As Slide")

    resp = pg_api_client.get(_slides_url(store["id"]), headers=auth_headers(user["id"]))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size"}
    assert body["total"] == 1
    assert body["page"] == 1 and body["page_size"] == 20
    assert len(body["items"]) == 1
    item = body["items"][0]
    # Exact existing slides response contract (field set/types) must remain unchanged
    assert set(item.keys()) == SLIDE_KEYS
    assert item["store_id"] == store["id"]
    assert item["title"] == "Mapped Hero As Slide"
    assert isinstance(item["position"], int)
    assert isinstance(item["is_active"], bool)
    assert isinstance(item["image_url"], str)
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
