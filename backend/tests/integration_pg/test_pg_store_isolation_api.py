"""B1.6 Step 2 (batch 4): PostgreSQL-backed HTTP API integration tests for store isolation.

Covers (per final corrected plan and actual endpoint contracts):
- List isolation: Store A member sees only Store A records/totals/pagination
- Detail isolation: authorized Store A member requesting Store B resource via Store A URL => 404 (not 403)
- Nested-resource isolation: product images, order items/status history, customer addresses do not leak
- Storefront content scoping: slides/sections/footer-links lists scoped to requested store
- Authorization distinction preserved: non-member/cross-store path access => 403; authorized foreign detail => 404

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.models.category import Category
from app.models.customer import Customer, CustomerAddress
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.product import Product, ProductImage
from app.models.storefront import StorefrontFooterLink, StorefrontSection, StorefrontSlide

from .helpers_pg import (
    assert_generic_403,
    assert_generic_404,
    auth_headers,
    create_staff,
    create_store,
    create_store_membership,
)

_TEST_AUTH_ENV = {
    "AUTH_JWT_SECRET": "b16-isolation-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.isolation.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-isolation-test-audience",
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


def _create_category(sf, *, store_id: str, name: str, slug: str) -> str:
    with sf() as db:
        row = Category(store_id=uuid.UUID(store_id), name=name, slug=slug, status="Active")
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_product(sf, *, store_id: str, name: str, slug: str) -> str:
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


def _create_product_image(sf, *, store_id: str, product_id: str, url: str, position: int, alt: str | None = None) -> str:
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


def _create_inventory_adjustment(sf, *, store_id: str, product_id: str, reason: str) -> str:
    with sf() as db:
        row = InventoryAdjustment(
            store_id=uuid.UUID(store_id),
            product_id=uuid.UUID(product_id),
            product_name="Prod",
            sku=None,
            adjustment_amount=1,
            previous_quantity=5,
            new_quantity=6,
            reason=reason,
            actor_id=None,
            actor_name=None,
            actor_email=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_customer(sf, *, store_id: str, email: str, full_name: str) -> str:
    with sf() as db:
        row = Customer(
            store_id=uuid.UUID(store_id),
            email=email,
            full_name=full_name,
            status="Active",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_customer_address(sf, *, store_id: str, customer_id: str, line1: str, is_default: bool = False) -> str:
    with sf() as db:
        row = CustomerAddress(
            store_id=uuid.UUID(store_id),
            customer_id=uuid.UUID(customer_id),
            label="Home" if is_default else None,
            line1=line1,
            line2=None,
            city="Austin",
            state=None,
            postal_code="78701",
            country="US",
            is_default=is_default,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_order(sf, *, store_id: str, order_number: str, customer_email: str) -> str:
    with sf() as db:
        row = Order(
            store_id=uuid.UUID(store_id),
            order_number=order_number,
            customer_name="Buyer",
            customer_email=customer_email,
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


def _create_order_item(
    sf, *, store_id: str, order_id: str, product_id: str | None, product_name: str, line_total: str = "10.00"
) -> str:
    with sf() as db:
        row = OrderItem(
            store_id=uuid.UUID(store_id),
            order_id=uuid.UUID(order_id),
            product_id=uuid.UUID(product_id) if product_id else None,
            product_name=product_name,
            product_sku=None,
            quantity=1,
            unit_price=Decimal(line_total),
            line_total=Decimal(line_total),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_order_status_history(
    sf, *, store_id: str, order_id: str, previous_status: str, new_status: str, reason: str
) -> str:
    with sf() as db:
        row = OrderStatusHistory(
            store_id=uuid.UUID(store_id),
            order_id=uuid.UUID(order_id),
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_slide(sf, *, store_id: str, title: str, position: int) -> str:
    with sf() as db:
        row = StorefrontSlide(
            store_id=uuid.UUID(store_id),
            title=title,
            image_url="https://example.com/slide.png",
            position=position,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_section(sf, *, store_id: str, title: str, position: int, config=None) -> str:
    with sf() as db:
        row = StorefrontSection(
            store_id=uuid.UUID(store_id),
            section_type="banner",
            title=title,
            position=position,
            is_active=True,
            config=config,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_footer_link(sf, *, store_id: str, label: str, position: int) -> str:
    with sf() as db:
        row = StorefrontFooterLink(
            store_id=uuid.UUID(store_id),
            label=label,
            url="https://example.com/footer",
            position=position,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _setup_two_stores(sf):
    user_a = create_staff(sf, email="store-a-owner@example.com", global_role="viewer", full_name="Store A Owner")
    user_b = create_staff(sf, email="store-b-owner@example.com", global_role="viewer", full_name="Store B Owner")
    store_a = create_store(sf, domain="isolation-a.example.com", name="Store A", owner="Owner A")
    store_b = create_store(sf, domain="isolation-b.example.com", name="Store B", owner="Owner B")
    create_store_membership(sf, store_id=store_a["id"], staff_user_id=user_a["id"], role="owner")
    create_store_membership(sf, store_id=store_b["id"], staff_user_id=user_b["id"], role="owner")
    return {"user_a": user_a, "user_b": user_b, "store_a": store_a, "store_b": store_b}


def _assert_list_only_store_a(resp, store_a_id: str, store_b_ids: set[str], expected_ids: set[str]):
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == expected_ids
    assert ids.isdisjoint(store_b_ids)
    assert all(item.get("store_id") == store_a_id for item in body["items"])
    assert body["total"] == len(expected_ids)
    assert body["page"] == 1
    assert body["page_size"] == 20


def test_list_isolation_across_in_scope_store_endpoints(pg_api_client, pg_api_session_factory):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_a, store_b = ctx["store_a"]["id"], ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])

    # Seed Store A
    cat_a1 = _create_category(pg_api_session_factory, store_id=store_a, name="Cat A1", slug="cat-a1")
    cat_a2 = _create_category(pg_api_session_factory, store_id=store_a, name="Cat A2", slug="cat-a2")
    prod_a1 = _create_product(pg_api_session_factory, store_id=store_a, name="Prod A1", slug="prod-a1")
    prod_a2 = _create_product(pg_api_session_factory, store_id=store_a, name="Prod A2", slug="prod-a2")
    adj_a1 = _create_inventory_adjustment(pg_api_session_factory, store_id=store_a, product_id=prod_a1, reason="a1")
    adj_a2 = _create_inventory_adjustment(pg_api_session_factory, store_id=store_a, product_id=prod_a2, reason="a2")
    cust_a1 = _create_customer(pg_api_session_factory, store_id=store_a, email="a1@example.com", full_name="Cust A1")
    cust_a2 = _create_customer(pg_api_session_factory, store_id=store_a, email="a2@example.com", full_name="Cust A2")
    ord_a1 = _create_order(pg_api_session_factory, store_id=store_a, order_number="ORD-000001", customer_email="a1@example.com")
    ord_a2 = _create_order(pg_api_session_factory, store_id=store_a, order_number="ORD-000002", customer_email="a2@example.com")
    slide_a = _create_slide(pg_api_session_factory, store_id=store_a, title="Slide A", position=1)
    sec_a = _create_section(pg_api_session_factory, store_id=store_a, title="Section A", position=1)
    foot_a = _create_footer_link(pg_api_session_factory, store_id=store_a, label="Footer A", position=1)

    # Seed Store B (must never leak)
    cat_b = _create_category(pg_api_session_factory, store_id=store_b, name="Cat B", slug="cat-b")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b, name="Prod B", slug="prod-b")
    adj_b = _create_inventory_adjustment(pg_api_session_factory, store_id=store_b, product_id=prod_b, reason="b")
    cust_b = _create_customer(pg_api_session_factory, store_id=store_b, email="b@example.com", full_name="Cust B")
    ord_b = _create_order(pg_api_session_factory, store_id=store_b, order_number="ORD-000001", customer_email="b@example.com")
    slide_b = _create_slide(pg_api_session_factory, store_id=store_b, title="Slide B", position=1)
    sec_b = _create_section(pg_api_session_factory, store_id=store_b, title="Section B", position=1)
    foot_b = _create_footer_link(pg_api_session_factory, store_id=store_b, label="Footer B", position=1)

    checks = [
        (f"/api/v1/stores/{store_a}/categories", {cat_a1, cat_a2}, {cat_b}),
        (f"/api/v1/stores/{store_a}/products", {prod_a1, prod_a2}, {prod_b}),
        (f"/api/v1/stores/{store_a}/inventory-adjustments", {adj_a1, adj_a2}, {adj_b}),
        (f"/api/v1/stores/{store_a}/customers", {cust_a1, cust_a2}, {cust_b}),
        (f"/api/v1/stores/{store_a}/orders", {ord_a1, ord_a2}, {ord_b}),
        (f"/api/v1/stores/{store_a}/storefront/slides", {slide_a}, {slide_b}),
        (f"/api/v1/stores/{store_a}/storefront/sections", {sec_a}, {sec_b}),
        (f"/api/v1/stores/{store_a}/storefront/footer-links", {foot_a}, {foot_b}),
    ]

    for path, expected_ids, foreign_ids in checks:
        resp = pg_api_client.get(path, headers=headers_a)
        _assert_list_only_store_a(resp, store_a, foreign_ids, expected_ids)

    # Pagination/totals must not reveal Store B records (page 2 empty, total remains Store A count).
    # Seed extra Store A categories to create a second page while Store B count stays separate.
    for i in range(3, 23):
        cid = _create_category(pg_api_session_factory, store_id=store_a, name=f"Cat A{i}", slug=f"cat-a{i}")
        # track only for total expectation on page 1 already checked above? we re-check below
        _ = cid
    resp_page1 = pg_api_client.get(f"/api/v1/stores/{store_a}/categories?page=1&page_size=20", headers=headers_a)
    assert resp_page1.status_code == 200
    body1 = resp_page1.json()
    assert body1["total"] == 22  # 2 original + 20 added
    assert len(body1["items"]) == 20
    assert cat_b not in {item["id"] for item in body1["items"]}
    assert all(item["store_id"] == store_a for item in body1["items"])

    resp_page2 = pg_api_client.get(f"/api/v1/stores/{store_a}/categories?page=2&page_size=20", headers=headers_a)
    assert resp_page2.status_code == 200
    body2 = resp_page2.json()
    assert body2["total"] == 22
    assert len(body2["items"]) == 2
    assert cat_b not in {item["id"] for item in body2["items"]}
    assert all(item["store_id"] == store_a for item in body2["items"])


def test_detail_isolation_foreign_store_resource_returns_404_not_403_for_authorized_member(
    pg_api_client, pg_api_session_factory
):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_a, store_b = ctx["store_a"]["id"], ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])

    # Seed Store B detail resources
    cat_b = _create_category(pg_api_session_factory, store_id=store_b, name="Cat B", slug="cat-b")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b, name="Prod B", slug="prod-b")
    adj_b = _create_inventory_adjustment(pg_api_session_factory, store_id=store_b, product_id=prod_b, reason="b")
    cust_b = _create_customer(pg_api_session_factory, store_id=store_b, email="b@example.com", full_name="Cust B")
    ord_b = _create_order(pg_api_session_factory, store_id=store_b, order_number="ORD-000001", customer_email="b@example.com")

    # Authorized Store A member requesting Store B resource IDs via Store A URL => 404 (no existence leak), not 403
    detail_paths = [
        f"/api/v1/stores/{store_a}/categories/{cat_b}",
        f"/api/v1/stores/{store_a}/products/{prod_b}",
        f"/api/v1/stores/{store_a}/inventory-adjustments/{adj_b}",
        f"/api/v1/stores/{store_a}/orders/{ord_b}",
        f"/api/v1/stores/{store_a}/customers/{cust_b}",
    ]
    for path in detail_paths:
        resp = pg_api_client.get(path, headers=headers_a)
        assert_generic_404(resp), path


def test_cross_store_path_access_without_membership_returns_403_not_404(
    pg_api_client, pg_api_session_factory
):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_b = ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])  # member of Store A only

    prod_b = _create_product(pg_api_session_factory, store_id=store_b, name="Prod B", slug="prod-b")
    ord_b = _create_order(pg_api_session_factory, store_id=store_b, order_number="ORD-000001", customer_email="b@example.com")

    # Authorization distinction: non-member/cross-store path access => 403
    assert_generic_403(pg_api_client.get(f"/api/v1/stores/{store_b}/products", headers=headers_a))
    assert_generic_403(pg_api_client.get(f"/api/v1/stores/{store_b}/products/{prod_b}", headers=headers_a))
    assert_generic_403(pg_api_client.get(f"/api/v1/stores/{store_b}/orders/{ord_b}", headers=headers_a))
    assert_generic_403(pg_api_client.get(f"/api/v1/stores/{store_b}/storefront/slides", headers=headers_a))


def test_nested_product_images_do_not_leak_across_stores_or_products(pg_api_client, pg_api_session_factory):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_a, store_b = ctx["store_a"]["id"], ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])

    prod_a = _create_product(pg_api_session_factory, store_id=store_a, name="Prod A", slug="prod-a")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b, name="Prod B", slug="prod-b")

    img_a = _create_product_image(
        pg_api_session_factory, store_id=store_a, product_id=prod_a, url="https://example.com/a.png", position=1, alt="A"
    )
    img_b = _create_product_image(
        pg_api_session_factory, store_id=store_b, product_id=prod_b, url="https://example.com/b.png", position=1, alt="B"
    )

    # Authorized detail for Store A product contains only Store A/product A images
    resp = pg_api_client.get(f"/api/v1/stores/{store_a}/products/{prod_a}", headers=headers_a)
    assert resp.status_code == 200
    images = resp.json()["images"]
    assert [im["id"] for im in images] == [img_a]
    assert all(im["store_id"] == store_a and im["product_id"] == prod_a for im in images)
    assert img_b not in [im["id"] for im in images]

    # Store B product detail is not accessible via Store A URL (404, no leak)
    assert_generic_404(pg_api_client.get(f"/api/v1/stores/{store_a}/products/{prod_b}", headers=headers_a))


def test_nested_order_items_and_status_history_do_not_leak_across_stores(pg_api_client, pg_api_session_factory):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_a, store_b = ctx["store_a"]["id"], ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])

    prod_a = _create_product(pg_api_session_factory, store_id=store_a, name="Prod A", slug="prod-a")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b, name="Prod B", slug="prod-b")
    ord_a = _create_order(pg_api_session_factory, store_id=store_a, order_number="ORD-000001", customer_email="a@example.com")
    ord_b = _create_order(pg_api_session_factory, store_id=store_b, order_number="ORD-000001", customer_email="b@example.com")

    item_a = _create_order_item(pg_api_session_factory, store_id=store_a, order_id=ord_a, product_id=prod_a, product_name="Item A")
    item_b = _create_order_item(pg_api_session_factory, store_id=store_b, order_id=ord_b, product_id=prod_b, product_name="Item B")
    hist_a = _create_order_status_history(
        pg_api_session_factory, store_id=store_a, order_id=ord_a, previous_status="Unfulfilled", new_status="Processing", reason="A"
    )
    hist_b = _create_order_status_history(
        pg_api_session_factory, store_id=store_b, order_id=ord_b, previous_status="Unfulfilled", new_status="Processing", reason="B"
    )

    resp = pg_api_client.get(f"/api/v1/stores/{store_a}/orders/{ord_a}", headers=headers_a)
    assert resp.status_code == 200
    detail = resp.json()
    assert [i["id"] for i in detail["items"]] == [item_a]
    assert [h["id"] for h in detail["status_history"]] == [hist_a]
    assert all(i["store_id"] == store_a and i["order_id"] == ord_a for i in detail["items"])
    assert all(h["store_id"] == store_a and h["order_id"] == ord_a for h in detail["status_history"])
    assert item_b not in [i["id"] for i in detail["items"]]
    assert hist_b not in [h["id"] for h in detail["status_history"]]

    # Foreign store order detail not accessible via Store A URL (404)
    assert_generic_404(pg_api_client.get(f"/api/v1/stores/{store_a}/orders/{ord_b}", headers=headers_a))


def test_nested_customer_addresses_do_not_leak_across_stores(pg_api_client, pg_api_session_factory):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_a, store_b = ctx["store_a"]["id"], ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])

    cust_a = _create_customer(pg_api_session_factory, store_id=store_a, email="a@example.com", full_name="Cust A")
    cust_b = _create_customer(pg_api_session_factory, store_id=store_b, email="b@example.com", full_name="Cust B")
    addr_a = _create_customer_address(pg_api_session_factory, store_id=store_a, customer_id=cust_a, line1="A Street", is_default=True)
    addr_b = _create_customer_address(pg_api_session_factory, store_id=store_b, customer_id=cust_b, line1="B Street", is_default=True)

    resp = pg_api_client.get(f"/api/v1/stores/{store_a}/customers/{cust_a}", headers=headers_a)
    assert resp.status_code == 200
    detail = resp.json()
    assert [a["id"] for a in detail["addresses"]] == [addr_a]
    assert all(a["store_id"] == store_a and a["customer_id"] == cust_a for a in detail["addresses"])
    assert addr_b not in [a["id"] for a in detail["addresses"]]

    # Foreign store customer detail not accessible via Store A URL (404)
    assert_generic_404(pg_api_client.get(f"/api/v1/stores/{store_a}/customers/{cust_b}", headers=headers_a))


def test_storefront_content_lists_remain_scoped_to_requested_store(pg_api_client, pg_api_session_factory):
    ctx = _setup_two_stores(pg_api_session_factory)
    store_a, store_b = ctx["store_a"]["id"], ctx["store_b"]["id"]
    headers_a = auth_headers(ctx["user_a"]["id"])

    slide_a = _create_slide(pg_api_session_factory, store_id=store_a, title="Slide A", position=1)
    slide_b = _create_slide(pg_api_session_factory, store_id=store_b, title="Slide B", position=1)
    sec_a = _create_section(pg_api_session_factory, store_id=store_a, title="Section A", position=1, config={"k": "a"})
    sec_b = _create_section(pg_api_session_factory, store_id=store_b, title="Section B", position=1, config={"k": "b"})
    foot_a = _create_footer_link(pg_api_session_factory, store_id=store_a, label="Footer A", position=1)
    foot_b = _create_footer_link(pg_api_session_factory, store_id=store_b, label="Footer B", position=1)

    for path, expected_id, foreign_id in [
        (f"/api/v1/stores/{store_a}/storefront/slides", slide_a, slide_b),
        (f"/api/v1/stores/{store_a}/storefront/sections", sec_a, sec_b),
        (f"/api/v1/stores/{store_a}/storefront/footer-links", foot_a, foot_b),
    ]:
        resp = pg_api_client.get(path, headers=headers_a)
        assert resp.status_code == 200
        body = resp.json()
        assert [item["id"] for item in body["items"]] == [expected_id]
        assert body["total"] == 1
        assert foreign_id not in [item["id"] for item in body["items"]]
        assert all(item["store_id"] == store_a for item in body["items"])
