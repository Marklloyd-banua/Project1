"""B1.6 Step 2 (batch 3): PostgreSQL-backed HTTP API integration tests for store authorization.

Covers (per final corrected plan and actual endpoint dependencies):
- Global roles vs store-membership roles tested independently
- owner/manager/viewer access for in-scope store read endpoints using require_store_member
- Non-members receive generic 403
- Platform administrators without store membership are denied store-scoped access (403)
- Store profile PATCH boundary (require_store_owner_or_manager): owner/manager allowed, viewer denied
- Storefront-settings GET behavior: existing row 200, missing row 404 without auto-creation,
  unauthenticated 401, unauthorized/non-member/platform-admin-without-membership 403
- Authentication failures (401) vs authorization failures (403) preserved

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.category import Category
from app.models.customer import Customer
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.order import Order
from app.models.product import Product
from app.models.storefront import StorefrontFooterLink, StorefrontSection, StorefrontSettings, StorefrontSlide

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

# Deterministic test-only auth env for token creation/validation in this module.
_TEST_AUTH_ENV = {
    "AUTH_JWT_SECRET": "b16-authz-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.authz.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-authz-test-audience",
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


def _seed_category(sf, *, store_id: str, name: str = "Cat", slug: str = "cat") -> str:
    with sf() as db:
        row = Category(store_id=uuid.UUID(store_id), name=name, slug=slug, status="Active")
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_product(sf, *, store_id: str, name: str = "Prod", slug: str = "prod") -> str:
    with sf() as db:
        row = Product(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            description="Desc",
            image="https://example.com/p.png",
            price=Decimal("10.00"),
            stock_quantity=5,
            low_stock_threshold=1,
            status="Active",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_inventory_adjustment(sf, *, store_id: str, product_id: str) -> str:
    with sf() as db:
        row = InventoryAdjustment(
            store_id=uuid.UUID(store_id),
            product_id=uuid.UUID(product_id),
            product_name="Prod",
            sku=None,
            adjustment_amount=1,
            previous_quantity=5,
            new_quantity=6,
            reason="seed",
            actor_id=None,
            actor_name=None,
            actor_email=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_order(sf, *, store_id: str) -> str:
    with sf() as db:
        row = Order(
            store_id=uuid.UUID(store_id),
            order_number="ORD-000001",
            customer_name="Buyer",
            customer_email="buyer@example.com",
            payment_status="Unpaid",
            fulfillment_status="Unfulfilled",
            subtotal=Decimal("10.00"),
            shipping_cost=Decimal("0.00"),
            discount=Decimal("0.00"),
            total=Decimal("10.00"),
            currency="USD",
            ship_line1="123 Main St",
            ship_city="Austin",
            ship_postal_code="78701",
            ship_country="US",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_customer(sf, *, store_id: str) -> str:
    with sf() as db:
        row = Customer(
            store_id=uuid.UUID(store_id),
            email="cust@example.com",
            full_name="Customer Name",
            status="Active",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_storefront_slide(sf, *, store_id: str) -> str:
    with sf() as db:
        row = StorefrontSlide(
            store_id=uuid.UUID(store_id),
            title="Slide",
            image_url="https://example.com/slide.png",
            position=1,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_storefront_section(sf, *, store_id: str) -> str:
    with sf() as db:
        row = StorefrontSection(
            store_id=uuid.UUID(store_id),
            section_type="banner",
            title="Section",
            position=1,
            is_active=True,
            config=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_storefront_footer_link(sf, *, store_id: str) -> str:
    with sf() as db:
        row = StorefrontFooterLink(
            store_id=uuid.UUID(store_id),
            label="Footer",
            url="https://example.com/footer",
            position=1,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _seed_storefront_settings(sf, *, store_id: str) -> str:
    with sf() as db:
        row = StorefrontSettings(
            store_id=uuid.UUID(store_id),
            is_published=True,
            theme={"mode": "light"},
            social_links={"twitter": "https://example.com/x"},
            contact_email="storefront@example.com",
            primary_color="#112233",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _build_context(sf, *, domain_suffix: str = "authz"):
    """Create a store with seeded entities for in-scope require_store_member read endpoints."""
    store = create_store(sf, domain=f"{domain_suffix}.example.com", name="Authz Store", owner="Owner")
    store_id = store["id"]

    category_id = _seed_category(sf, store_id=store_id, name="Category A", slug="category-a")
    product_id = _seed_product(sf, store_id=store_id, name="Product A", slug="product-a")
    adjustment_id = _seed_inventory_adjustment(sf, store_id=store_id, product_id=product_id)
    order_id = _seed_order(sf, store_id=store_id)
    customer_id = _seed_customer(sf, store_id=store_id)
    _seed_storefront_slide(sf, store_id=store_id)
    _seed_storefront_section(sf, store_id=store_id)
    _seed_storefront_footer_link(sf, store_id=store_id)

    read_endpoints = [
        ("GET", f"/api/v1/stores/{store_id}"),
        ("GET", f"/api/v1/stores/{store_id}/members"),
        ("GET", f"/api/v1/stores/{store_id}/workspace/summary"),
        ("GET", f"/api/v1/stores/{store_id}/categories"),
        ("GET", f"/api/v1/stores/{store_id}/categories/{category_id}"),
        ("GET", f"/api/v1/stores/{store_id}/products"),
        ("GET", f"/api/v1/stores/{store_id}/products/{product_id}"),
        ("GET", f"/api/v1/stores/{store_id}/inventory-adjustments"),
        ("GET", f"/api/v1/stores/{store_id}/inventory-adjustments/{adjustment_id}"),
        ("GET", f"/api/v1/stores/{store_id}/orders"),
        ("GET", f"/api/v1/stores/{store_id}/orders/{order_id}"),
        ("GET", f"/api/v1/stores/{store_id}/customers"),
        ("GET", f"/api/v1/stores/{store_id}/customers/{customer_id}"),
        ("GET", f"/api/v1/stores/{store_id}/storefront/slides"),
        ("GET", f"/api/v1/stores/{store_id}/storefront/sections"),
        ("GET", f"/api/v1/stores/{store_id}/storefront/footer-links"),
    ]

    return {
        "store_id": store_id,
        "read_endpoints": read_endpoints,
    }


def _request(client, method: str, path: str, **kwargs):
    return getattr(client, method.lower())(path, **kwargs)


@pytest.mark.parametrize("global_role", ["administrator", "manager", "viewer"])
@pytest.mark.parametrize("store_role", ["owner", "manager", "viewer"])
def test_store_membership_roles_authorize_require_store_member_reads_independently_of_global_role(
    pg_api_client, pg_api_session_factory, global_role, store_role
):
    # Global role and store-membership role are independent: access is determined by store membership
    # (and endpoint store-role dependency), not by global platform-admin privilege.
    ctx = _build_context(pg_api_session_factory, domain_suffix=f"member-{global_role}-{store_role}")
    user = create_staff(
        pg_api_session_factory,
        email=f"{global_role}-{store_role}@example.com",
        global_role=global_role,
        status="Active",
    )
    create_store_membership(
        pg_api_session_factory,
        store_id=ctx["store_id"],
        staff_user_id=user["id"],
        role=store_role,
    )
    headers = auth_headers(user["id"])

    for method, path in ctx["read_endpoints"]:
        resp = _request(pg_api_client, method, path, headers=headers)
        assert resp.status_code == 200, f"{method} {path} for global={global_role} store={store_role}"


def test_in_scope_store_read_endpoints_require_authentication_401_not_403(
    pg_api_client, pg_api_session_factory
):
    ctx = _build_context(pg_api_session_factory, domain_suffix="unauth-read")
    for method, path in ctx["read_endpoints"]:
        # Missing bearer
        resp_missing = _request(pg_api_client, method, path)
        assert_generic_401(resp_missing)
        # Malformed/invalid bearer token
        resp_invalid = _request(
            pg_api_client, method, path, headers=auth_headers_for_token("not-a-jwt")
        )
        assert_generic_401(resp_invalid)


def test_nonmember_receives_generic_403_for_in_scope_store_read_endpoints(
    pg_api_client, pg_api_session_factory
):
    ctx = _build_context(pg_api_session_factory, domain_suffix="nonmember-read")
    nonmember = create_staff(
        pg_api_session_factory,
        email="nonmember-authz@example.com",
        global_role="viewer",
        status="Active",
    )
    headers = auth_headers(nonmember["id"])
    for method, path in ctx["read_endpoints"]:
        resp = _request(pg_api_client, method, path, headers=headers)
        assert_generic_403(resp), f"{method} {path}"


def test_platform_admin_without_store_membership_denied_403_for_in_scope_store_read_endpoints(
    pg_api_client, pg_api_session_factory
):
    # Platform administrator global role does NOT bypass store membership requirements.
    ctx = _build_context(pg_api_session_factory, domain_suffix="admin-nomember-read")
    platform_admin = create_staff(
        pg_api_session_factory,
        email="platform-admin-no-membership@example.com",
        global_role="administrator",
        status="Active",
    )
    headers = auth_headers(platform_admin["id"])
    for method, path in ctx["read_endpoints"]:
        resp = _request(pg_api_client, method, path, headers=headers)
        assert_generic_403(resp), f"{method} {path}"


def test_store_profile_patch_boundary_owner_and_manager_allowed_viewer_denied(
    pg_api_client, pg_api_session_factory
):
    # Endpoint dependency: require_store_owner_or_manager (actual contract).
    store = create_store(pg_api_session_factory, domain="patch-boundary.example.com", name="Patch Store", owner="Owner")

    owner = create_staff(pg_api_session_factory, email="owner-patch@example.com", global_role="viewer")
    manager = create_staff(pg_api_session_factory, email="manager-patch@example.com", global_role="viewer")
    viewer = create_staff(pg_api_session_factory, email="viewer-patch@example.com", global_role="viewer")
    platform_admin_no_membership = create_staff(
        pg_api_session_factory, email="admin-nomember-patch@example.com", global_role="administrator"
    )
    nonmember = create_staff(pg_api_session_factory, email="nonmember-patch@example.com", global_role="viewer")

    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=owner["id"], role="owner")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=manager["id"], role="manager")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=viewer["id"], role="viewer")

    url = f"/api/v1/stores/{store['id']}"

    # Owner can update (200)
    owner_resp = pg_api_client.patch(url, headers=auth_headers(owner["id"]), json={"name": "Owner Updated"})
    assert owner_resp.status_code == 200
    assert owner_resp.json()["name"] == "Owner Updated"

    # Manager can update (200)
    manager_resp = pg_api_client.patch(url, headers=auth_headers(manager["id"]), json={"name": "Manager Updated"})
    assert manager_resp.status_code == 200
    assert manager_resp.json()["name"] == "Manager Updated"

    # Viewer denied (403)
    assert_generic_403(
        pg_api_client.patch(url, headers=auth_headers(viewer["id"]), json={"name": "Viewer Update"})
    )

    # Non-member denied (403)
    assert_generic_403(
        pg_api_client.patch(url, headers=auth_headers(nonmember["id"]), json={"name": "Nonmember Update"})
    )

    # Platform admin without store membership denied (403), no bypass
    assert_generic_403(
        pg_api_client.patch(
            url,
            headers=auth_headers(platform_admin_no_membership["id"]),
            json={"name": "Admin Update"},
        )
    )

    # Authentication failure remains 401 (not 403)
    assert_generic_401(pg_api_client.patch(url, json={"name": "Unauth Update"}))
    assert_generic_401(
        pg_api_client.patch(url, headers=auth_headers_for_token("not-a-jwt"), json={"name": "BadToken"})
    )


def test_storefront_settings_get_existing_row_returns_200_for_authorized_member(
    pg_api_client, pg_api_session_factory
):
    store = create_store(pg_api_session_factory, domain="sf-settings-ok.example.com")
    member = create_staff(pg_api_session_factory, email="sf-member@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=member["id"], role="viewer")
    settings_id = _seed_storefront_settings(pg_api_session_factory, store_id=store["id"])

    resp = pg_api_client.get(
        f"/api/v1/stores/{store['id']}/storefront-settings",
        headers=auth_headers(member["id"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == settings_id
    assert body["store_id"] == store["id"]
    assert set(body.keys()) == {
        "id",
        "store_id",
        "is_published",
        "theme",
        "social_links",
        "contact_email",
        "primary_color",
        "created_at",
        "updated_at",
    }


def test_storefront_settings_get_missing_row_returns_404_without_auto_creation(
    pg_api_client, pg_api_session_factory
):
    store = create_store(pg_api_session_factory, domain="sf-settings-missing.example.com")
    member = create_staff(pg_api_session_factory, email="sf-missing@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=member["id"], role="owner")
    headers = auth_headers(member["id"])
    url = f"/api/v1/stores/{store['id']}/storefront-settings"

    resp = pg_api_client.get(url, headers=headers)
    assert_generic_404(resp)

    with pg_api_session_factory() as db:
        rows = db.execute(
            select(StorefrontSettings).where(StorefrontSettings.store_id == uuid.UUID(store["id"]))
        ).scalars().all()
        assert rows == []

    # No auto-creation on repeated authorized read
    resp_again = pg_api_client.get(url, headers=headers)
    assert_generic_404(resp_again)
    with pg_api_session_factory() as db:
        rows_after = db.execute(
            select(StorefrontSettings).where(StorefrontSettings.store_id == uuid.UUID(store["id"]))
        ).scalars().all()
        assert rows_after == []


def test_storefront_settings_get_authorization_and_authentication_failures(
    pg_api_client, pg_api_session_factory
):
    store = create_store(pg_api_session_factory, domain="sf-settings-auth.example.com")
    _seed_storefront_settings(pg_api_session_factory, store_id=store["id"])
    url = f"/api/v1/stores/{store['id']}/storefront-settings"

    # Authentication failures (401), not 403
    assert_generic_401(pg_api_client.get(url))
    assert_generic_401(pg_api_client.get(url, headers=auth_headers_for_token("not-a-jwt")))

    # Unauthorized user (authenticated non-member) => 403
    nonmember = create_staff(pg_api_session_factory, email="sf-nonmember@example.com", global_role="viewer")
    assert_generic_403(pg_api_client.get(url, headers=auth_headers(nonmember["id"])))

    # Platform administrator without store membership => 403 (no bypass)
    platform_admin = create_staff(
        pg_api_session_factory, email="sf-admin-nomember@example.com", global_role="administrator"
    )
    assert_generic_403(pg_api_client.get(url, headers=auth_headers(platform_admin["id"])))

    # Cross-store path access without membership => 403
    other_store = create_store(pg_api_session_factory, domain="sf-settings-other.example.com")
    _seed_storefront_settings(pg_api_session_factory, store_id=other_store["id"])
    member_of_first = create_staff(pg_api_session_factory, email="sf-cross@example.com", global_role="viewer")
    create_store_membership(
        pg_api_session_factory, store_id=store["id"], staff_user_id=member_of_first["id"], role="viewer"
    )
    assert_generic_403(
        pg_api_client.get(
            f"/api/v1/stores/{other_store['id']}/storefront-settings",
            headers=auth_headers(member_of_first["id"]),
        )
    )
