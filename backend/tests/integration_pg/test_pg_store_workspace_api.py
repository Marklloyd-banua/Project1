"""B1.6 Step 2 (batch 5): PostgreSQL-backed HTTP API integration tests for store workspace summary.

Covers (per final corrected plan and actual endpoint/schema contract):
- Successful workspace summary for authorized Store A member (status/structure/values vs seeded DB)
- Store isolation: Store A summary includes only Store A records; Store B records do not affect totals
- Empty workspace: zero counts/expected fields for store with no relevant records
- Authorization: authenticated nonmember => 403; unauthenticated/invalid token => generic 401
- Response correctness: exact fields/types/values per actual StoreWorkspaceSummaryResponse contract
  (no nested/recent items or monetary fields in this endpoint)

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.models.category import Category
from app.models.customer import Customer
from app.models.order import Order
from app.models.product import Product

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
    "AUTH_JWT_SECRET": "b16-workspace-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.workspace.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-workspace-test-audience",
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


def _summary_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/workspace/summary"


def _create_category(sf, *, store_id: str, name: str, slug: str, status: str = "Active") -> str:
    with sf() as db:
        row = Category(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_product(
    sf,
    *,
    store_id: str,
    name: str,
    slug: str,
    status: str = "Active",
    price: str = "10.00",
) -> str:
    with sf() as db:
        row = Product(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            status=status,
            price=Decimal(price),
            description="Desc",
            image="https://example.com/p.png",
            stock_quantity=0,
            low_stock_threshold=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_customer(sf, *, store_id: str, email: str, full_name: str = "Customer", status: str = "Active") -> str:
    with sf() as db:
        row = Customer(
            store_id=uuid.UUID(store_id),
            email=email,
            full_name=full_name,
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_order(
    sf,
    *,
    store_id: str,
    order_number: str,
    payment_status: str = "Unpaid",
    fulfillment_status: str = "Unfulfilled",
    customer_email: str = "buyer@example.com",
) -> str:
    with sf() as db:
        row = Order(
            store_id=uuid.UUID(store_id),
            order_number=order_number,
            customer_name="Buyer",
            customer_email=customer_email,
            payment_status=payment_status,
            fulfillment_status=fulfillment_status,
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


def _assert_summary_contract_and_types(body: dict, expected_store_id: str) -> None:
    # Actual response contract: only these aggregate count fields (no nested/recent items, no monetary fields).
    assert set(body.keys()) == {
        "store_id",
        "members_count",
        "categories_count",
        "products_count",
        "active_products_count",
        "customers_count",
        "orders_count",
    }
    assert body["store_id"] == expected_store_id
    for key in (
        "members_count",
        "categories_count",
        "products_count",
        "active_products_count",
        "customers_count",
        "orders_count",
    ):
        assert isinstance(body[key], int), key
        assert body[key] >= 0, key


def test_workspace_summary_success_for_store_member_matches_seeded_store_a(pg_api_client, pg_api_session_factory):
    user_a = create_staff(pg_api_session_factory, email="owner-a-ws@example.com", global_role="viewer")
    store_a = create_store(pg_api_session_factory, domain="store-a-ws.example.com", name="Store A")
    create_store_membership(pg_api_session_factory, store_id=store_a["id"], staff_user_id=user_a["id"], role="owner")
    extra_member_a = create_staff(pg_api_session_factory, email="member-a2-ws@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store_a["id"], staff_user_id=extra_member_a["id"], role="manager")

    # Store A seeded records (distinct statuses/counting rules per endpoint contract)
    _create_category(pg_api_session_factory, store_id=store_a["id"], name="Cat A1", slug="cat-a1", status="Active")
    _create_category(pg_api_session_factory, store_id=store_a["id"], name="Cat A2", slug="cat-a2", status="Draft")
    _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A1", slug="prod-a1", status="Active")
    _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A2", slug="prod-a2", status="Draft")
    _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A3", slug="prod-a3", status="Draft")
    _create_customer(pg_api_session_factory, store_id=store_a["id"], email="cust-a1@example.com", status="Active")
    _create_customer(pg_api_session_factory, store_id=store_a["id"], email="cust-a2@example.com", status="Suspended")
    _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000001", payment_status="Paid", fulfillment_status="Delivered")
    _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000002", payment_status="Unpaid", fulfillment_status="Unfulfilled")
    _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000003", payment_status="Failed", fulfillment_status="Cancelled")
    _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000004", payment_status="Refunded", fulfillment_status="Returned")

    resp = pg_api_client.get(_summary_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()
    _assert_summary_contract_and_types(body, store_a["id"])

    # Values derived from seeded Store A DB records (actual counting rules)
    assert body["members_count"] == 2
    assert body["categories_count"] == 2
    assert body["products_count"] == 3
    assert body["active_products_count"] == 1
    assert body["customers_count"] == 2  # all statuses counted
    assert body["orders_count"] == 4     # all statuses counted


def test_workspace_summary_isolated_to_store_a_and_ignores_store_b(pg_api_client, pg_api_session_factory):
    user_a = create_staff(pg_api_session_factory, email="iso-a@example.com", global_role="viewer")
    user_b = create_staff(pg_api_session_factory, email="iso-b@example.com", global_role="viewer")
    store_a = create_store(pg_api_session_factory, domain="iso-a-ws.example.com", name="Store A")
    store_b = create_store(pg_api_session_factory, domain="iso-b-ws.example.com", name="Store B")

    create_store_membership(pg_api_session_factory, store_id=store_a["id"], staff_user_id=user_a["id"], role="owner")
    extra_a = create_staff(pg_api_session_factory, email="iso-a2@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store_a["id"], staff_user_id=extra_a["id"], role="manager")

    create_store_membership(pg_api_session_factory, store_id=store_b["id"], staff_user_id=user_b["id"], role="owner")
    extra_b = create_staff(pg_api_session_factory, email="iso-b2@example.com", global_role="viewer")
    create_store_membership(pg_api_session_factory, store_id=store_b["id"], staff_user_id=extra_b["id"], role="viewer")

    # Store A data
    _create_category(pg_api_session_factory, store_id=store_a["id"], name="Cat A1", slug="cat-a1", status="Active")
    _create_category(pg_api_session_factory, store_id=store_a["id"], name="Cat A2", slug="cat-a2", status="Draft")
    _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A1", slug="prod-a1", status="Active")
    _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A2", slug="prod-a2", status="Draft")
    _create_customer(pg_api_session_factory, store_id=store_a["id"], email="cust-a1@example.com", status="Active")
    _create_customer(pg_api_session_factory, store_id=store_a["id"], email="cust-a2@example.com", status="Suspended")
    _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000001", payment_status="Paid", fulfillment_status="Delivered")

    # Store B data (must not affect Store A totals)
    _create_category(pg_api_session_factory, store_id=store_b["id"], name="Cat B1", slug="cat-b1", status="Active")
    _create_product(pg_api_session_factory, store_id=store_b["id"], name="Prod B1", slug="prod-b1", status="Active")
    _create_product(pg_api_session_factory, store_id=store_b["id"], name="Prod B2", slug="prod-b2", status="Draft")
    _create_customer(pg_api_session_factory, store_id=store_b["id"], email="cust-b1@example.com", status="Active")
    _create_order(pg_api_session_factory, store_id=store_b["id"], order_number="ORD-100001", payment_status="Unpaid", fulfillment_status="Unfulfilled")
    _create_order(pg_api_session_factory, store_id=store_b["id"], order_number="ORD-100002", payment_status="Failed", fulfillment_status="Cancelled")

    resp = pg_api_client.get(_summary_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()
    _assert_summary_contract_and_types(body, store_a["id"])
    assert body == {
        "store_id": store_a["id"],
        "members_count": 2,
        "categories_count": 2,
        "products_count": 2,
        "active_products_count": 1,
        "customers_count": 2,
        "orders_count": 1,
    }

    # No nested/recent item collections exist in this contract; counts above prove Store B exclusion.
    assert "items" not in body
    assert "recent" not in body


def test_workspace_summary_empty_store_returns_zero_counts_per_contract(pg_api_client, pg_api_session_factory):
    user = create_staff(pg_api_session_factory, email="empty-ws@example.com", global_role="viewer")
    store = create_store(pg_api_session_factory, domain="empty-ws.example.com", name="Empty Store")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=user["id"], role="owner")

    resp = pg_api_client.get(_summary_url(store["id"]), headers=auth_headers(user["id"]))
    assert resp.status_code == 200
    body = resp.json()
    _assert_summary_contract_and_types(body, store["id"])
    assert body == {
        "store_id": store["id"],
        "members_count": 1,  # authorized member exists
        "categories_count": 0,
        "products_count": 0,
        "active_products_count": 0,
        "customers_count": 0,
        "orders_count": 0,
    }


def test_workspace_summary_authorization_and_authentication(pg_api_client, pg_api_session_factory):
    member = create_staff(pg_api_session_factory, email="viewer-ws@example.com", global_role="viewer")
    nonmember = create_staff(pg_api_session_factory, email="nonmember-ws@example.com", global_role="viewer")
    store = create_store(pg_api_session_factory, domain="authz-ws.example.com", name="Authz Store")
    create_store_membership(pg_api_session_factory, store_id=store["id"], staff_user_id=member["id"], role="viewer")

    # Authorized member (viewer) can read
    ok = pg_api_client.get(_summary_url(store["id"]), headers=auth_headers(member["id"]))
    assert ok.status_code == 200
    _assert_summary_contract_and_types(ok.json(), store["id"])

    # Authenticated non-member => 403 (generic)
    assert_generic_403(pg_api_client.get(_summary_url(store["id"]), headers=auth_headers(nonmember["id"])))

    # Unauthenticated => 401 (generic)
    assert_generic_401(pg_api_client.get(_summary_url(store["id"])))

    # Invalid token => 401 (generic, not 403)
    assert_generic_401(
        pg_api_client.get(_summary_url(store["id"]), headers=auth_headers_for_token("not-a-jwt"))
    )
