"""B1.6 Step 2 (batch 9): PostgreSQL-backed HTTP API integration tests for store orders.

Covers (per approved corrected plan and actual endpoint/schema contracts):
- Order list envelope, exact summary schema/field types/nullability, UUID/datetime serialization,
  and monetary Decimal string serialization
- Store A list results and totals exclude Store B orders
- Pagination defaults, custom pages, invalid parameters (422), and out-of-range behavior
  (200 with empty items and accurate total)
- Actual deterministic endpoint ordering including every sort key and tie-breaker:
  list orders by created_at DESC, id DESC; nested items/history by created_at ASC, id ASC
- Detail behavior: existing order 200, nonexistent 404, foreign-store order via authorized Store A path 404 (not 403)
- Nested order items and status-history response structure, ownership, and store/order scoping
- AuthN/AuthZ: authorized member, nonmember 403, missing/invalid bearer 401 with generic semantics
- PostgreSQL-compatible seed data respecting model/database constraints, FKs, and snapshot semantics

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.models.order import Order, OrderItem, OrderStatusHistory

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
    "AUTH_JWT_SECRET": "b16-orders-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.orders.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-orders-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

ORDER_SUMMARY_KEYS = {
    "id",
    "store_id",
    "order_number",
    "customer_id",
    "customer_name",
    "customer_email",
    "customer_phone",
    "payment_status",
    "fulfillment_status",
    "subtotal",
    "shipping_cost",
    "discount",
    "total",
    "currency",
    "created_at",
    "updated_at",
}
ORDER_DETAIL_KEYS = ORDER_SUMMARY_KEYS | {
    "cart_id",
    "ship_line1",
    "ship_line2",
    "ship_city",
    "ship_state",
    "ship_postal_code",
    "ship_country",
    "notes",
    "items",
    "status_history",
}
ORDER_ITEM_KEYS = {
    "id",
    "store_id",
    "order_id",
    "product_id",
    "product_name",
    "product_sku",
    "quantity",
    "unit_price",
    "line_total",
    "created_at",
    "updated_at",
}
ORDER_STATUS_HISTORY_KEYS = {
    "id",
    "store_id",
    "order_id",
    "previous_status",
    "new_status",
    "reason",
    "actor_id",
    "actor_name",
    "actor_email",
    "created_at",
    "updated_at",
}
MONEY_SUMMARY_FIELDS = ("subtotal", "shipping_cost", "discount", "total")
MONEY_ITEM_FIELDS = ("unit_price", "line_total")


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
    return f"/api/v1/stores/{store_id}/orders"


def _detail_url(store_id: str, order_id: str) -> str:
    return f"/api/v1/stores/{store_id}/orders/{order_id}"


def _setup_store_a_member(sf, *, domain: str = "ord-a.example.com"):
    user = create_staff(sf, email=f"member-{domain}", global_role="viewer")
    store = create_store(sf, domain=domain, name="Store A", owner="Owner A")
    create_store_membership(sf, store_id=store["id"], staff_user_id=user["id"], role="viewer")
    return user, store


def _create_order(
    sf,
    *,
    store_id: str,
    order_number: str = "ORD-000001",
    customer_id: str | None = None,
    cart_id: str | None = None,
    customer_name: str = "Cust Name",
    customer_email: str = "cust@example.com",
    customer_phone: str | None = None,
    payment_status: str = "Unpaid",
    fulfillment_status: str = "Unfulfilled",
    subtotal: Decimal = Decimal("10.00"),
    shipping_cost: Decimal = Decimal("2.00"),
    discount: Decimal = Decimal("1.00"),
    total: Decimal = Decimal("11.00"),
    currency: str = "USD",
    ship_line1: str = "123 Main",
    ship_line2: str | None = None,
    ship_city: str = "City",
    ship_state: str | None = None,
    ship_postal_code: str = "12345",
    ship_country: str = "US",
    notes: str | None = None,
) -> str:
    with sf() as db:
        row = Order(
            store_id=uuid.UUID(store_id),
            order_number=order_number,
            customer_id=uuid.UUID(customer_id) if customer_id else None,
            cart_id=uuid.UUID(cart_id) if cart_id else None,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            payment_status=payment_status,
            fulfillment_status=fulfillment_status,
            subtotal=subtotal,
            shipping_cost=shipping_cost,
            discount=discount,
            total=total,
            currency=currency,
            ship_line1=ship_line1,
            ship_line2=ship_line2,
            ship_city=ship_city,
            ship_state=ship_state,
            ship_postal_code=ship_postal_code,
            ship_country=ship_country,
            notes=notes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_order_item(
    sf,
    *,
    store_id: str,
    order_id: str,
    product_id: str | None = None,
    product_name: str = "Item",
    product_sku: str | None = None,
    quantity: int = 1,
    unit_price: Decimal = Decimal("10.00"),
    line_total: Decimal = Decimal("10.00"),
) -> str:
    with sf() as db:
        row = OrderItem(
            store_id=uuid.UUID(store_id),
            order_id=uuid.UUID(order_id),
            product_id=uuid.UUID(product_id) if product_id else None,
            product_name=product_name,
            product_sku=product_sku,
            quantity=quantity,
            unit_price=unit_price,
            line_total=line_total,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_order_status_history(
    sf,
    *,
    store_id: str,
    order_id: str,
    previous_status: str = "Unfulfilled",
    new_status: str = "Processing",
    reason: str = "Started",
    actor_id: str | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> str:
    with sf() as db:
        row = OrderStatusHistory(
            store_id=uuid.UUID(store_id),
            order_id=uuid.UUID(order_id),
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _set_created_at(sf, model, row_id: str, created_at: datetime) -> None:
    with sf() as db:
        row = db.get(model, uuid.UUID(row_id))
        assert row is not None
        row.created_at = created_at
        db.commit()


def _assert_order_summary_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == ORDER_SUMMARY_KEYS
    assert item["store_id"] == expected_store_id
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["order_number"], str)
    assert item["customer_id"] is None or isinstance(item["customer_id"], str)
    assert isinstance(item["customer_name"], str)
    assert isinstance(item["customer_email"], str)
    assert item["customer_phone"] is None or isinstance(item["customer_phone"], str)
    assert isinstance(item["payment_status"], str)
    assert isinstance(item["fulfillment_status"], str)
    for f in MONEY_SUMMARY_FIELDS:
        assert isinstance(item[f], str), f
    assert isinstance(item["currency"], str)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    if item["customer_id"] is not None:
        uuid.UUID(item["customer_id"])


def _assert_order_item_contract(item: dict, expected_store_id: str, expected_order_id: str) -> None:
    assert set(item.keys()) == ORDER_ITEM_KEYS
    assert item["store_id"] == expected_store_id
    assert item["order_id"] == expected_order_id
    assert isinstance(item["id"], str) and item["id"]
    assert item["product_id"] is None or isinstance(item["product_id"], str)
    assert isinstance(item["product_name"], str)
    assert item["product_sku"] is None or isinstance(item["product_sku"], str)
    assert isinstance(item["quantity"], int)
    for f in MONEY_ITEM_FIELDS:
        assert isinstance(item[f], str), f
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    uuid.UUID(item["order_id"])
    if item["product_id"] is not None:
        uuid.UUID(item["product_id"])


def _assert_order_history_contract(item: dict, expected_store_id: str, expected_order_id: str) -> None:
    assert set(item.keys()) == ORDER_STATUS_HISTORY_KEYS
    assert item["store_id"] == expected_store_id
    assert item["order_id"] == expected_order_id
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["previous_status"], str)
    assert isinstance(item["new_status"], str)
    assert isinstance(item["reason"], str)
    assert item["actor_id"] is None or isinstance(item["actor_id"], str)
    assert item["actor_name"] is None or isinstance(item["actor_name"], str)
    assert item["actor_email"] is None or isinstance(item["actor_email"], str)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    uuid.UUID(item["order_id"])
    if item["actor_id"] is not None:
        uuid.UUID(item["actor_id"])


def test_orders_list_envelope_schema_scoping_totals_and_monetary_serialization(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="ord-list-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="ord-list-b.example.com", name="Store B", owner="Owner B")

    order_a = _create_order(
        pg_api_session_factory,
        store_id=store_a["id"],
        order_number="ORD-000099",
        customer_id=None,
        cart_id=None,
        customer_name="Snapshot Cust",
        customer_email="cust@example.com",
        customer_phone=None,
        payment_status="Paid",
        fulfillment_status="Shipped",
        subtotal=Decimal("100.10"),
        shipping_cost=Decimal("5.00"),
        discount=Decimal("0.10"),
        total=Decimal("105.00"),
        currency="USD",
    )
    _create_order(
        pg_api_session_factory,
        store_id=store_b["id"],
        order_number="ORD-000099",
        subtotal=Decimal("9.99"),
        shipping_cost=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("9.99"),
    )

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"items", "total", "page", "page_size"}
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]
    _assert_order_summary_contract(item, store_a["id"])
    assert item["id"] == order_a
    assert item["customer_id"] is None
    assert item["customer_phone"] is None
    assert item["payment_status"] == "Paid"
    assert item["fulfillment_status"] == "Shipped"
    assert item["subtotal"] == "100.10"
    assert item["shipping_cost"] == "5.00"
    assert item["discount"] == "0.10"
    assert item["total"] == "105.00"
    assert all(isinstance(item[f], str) for f in MONEY_SUMMARY_FIELDS)
    assert all(it["store_id"] == store_a["id"] for it in body["items"])


def test_orders_list_pagination_defaults_custom_invalid_and_out_of_range(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="ord-page-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="ord-page-b.example.com", name="Store B", owner="Owner B")

    for i in range(25):
        _create_order(
            pg_api_session_factory,
            store_id=store_a["id"],
            order_number=f"ORD-{i:06d}",
            subtotal=Decimal("10.00"),
            shipping_cost=Decimal("0.00"),
            discount=Decimal("0.00"),
            total=Decimal("10.00"),
        )
    for i in range(5):
        _create_order(
            pg_api_session_factory,
            store_id=store_b["id"],
            order_number=f"ORD-B{i:05d}",
            subtotal=Decimal("10.00"),
            shipping_cost=Decimal("0.00"),
            discount=Decimal("0.00"),
            total=Decimal("10.00"),
        )

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


def test_orders_list_deterministic_ordering_created_at_desc_then_id_desc(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="ord-order.example.com")

    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # older
    t2 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)  # newer

    o1 = _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000001")
    o2 = _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000002")
    o3 = _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000003")
    _set_created_at(pg_api_session_factory, Order, o1, t1)
    _set_created_at(pg_api_session_factory, Order, o2, t2)
    _set_created_at(pg_api_session_factory, Order, o3, t2)  # tie on created_at -> id DESC

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]

    # Primary: different created_at values -> created_at DESC (t2 group before t1)
    assert ids[-1] == o1
    assert set(ids[:2]) == {o2, o3}
    # Tie-breaker: equal created_at -> id DESC (exercised independently within t2 group)
    assert ids[0] > ids[1]


def test_order_detail_existing_schema_nested_scoping_and_nested_ordering(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="ord-detail-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="ord-detail-b.example.com", name="Store B", owner="Owner B")

    order_a = _create_order(
        pg_api_session_factory,
        store_id=store_a["id"],
        order_number="ORD-000050",
        customer_id=None,
        cart_id=None,
        customer_name="Detail Cust",
        customer_email="detail@example.com",
        customer_phone=None,
        payment_status="Paid",
        fulfillment_status="Processing",
        subtotal=Decimal("20.00"),
        shipping_cost=Decimal("3.00"),
        discount=Decimal("1.00"),
        total=Decimal("22.00"),
        currency="USD",
        ship_line1="Line 1",
        ship_line2=None,
        ship_city="Metropolis",
        ship_state=None,
        ship_postal_code="99999",
        ship_country="US",
        notes=None,
    )
    empty_order_a = _create_order(
        pg_api_session_factory,
        store_id=store_a["id"],
        order_number="ORD-000051",
        subtotal=Decimal("0.00"),
        shipping_cost=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("0.00"),
    )
    order_b = _create_order(
        pg_api_session_factory,
        store_id=store_b["id"],
        order_number="ORD-000050",
        subtotal=Decimal("7.00"),
        shipping_cost=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("7.00"),
    )

    # Nested items/history for Store A order (exercise created_at ASC primary and id ASC tie-breaker)
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)
    i1 = _create_order_item(
        pg_api_session_factory, store_id=store_a["id"], order_id=order_a,
        product_id=None, product_name="I1", product_sku=None,
        quantity=1, unit_price=Decimal("5.00"), line_total=Decimal("5.00"),
    )
    i2 = _create_order_item(
        pg_api_session_factory, store_id=store_a["id"], order_id=order_a,
        product_id=None, product_name="I2", product_sku="SKU-2",
        quantity=2, unit_price=Decimal("5.00"), line_total=Decimal("10.00"),
    )
    i3 = _create_order_item(
        pg_api_session_factory, store_id=store_a["id"], order_id=order_a,
        product_id=None, product_name="I3", product_sku="SKU-3",
        quantity=1, unit_price=Decimal("5.00"), line_total=Decimal("5.00"),
    )
    _set_created_at(pg_api_session_factory, OrderItem, i1, t1)
    _set_created_at(pg_api_session_factory, OrderItem, i2, t2)
    _set_created_at(pg_api_session_factory, OrderItem, i3, t2)  # tie -> id ASC

    h1 = _create_order_status_history(
        pg_api_session_factory, store_id=store_a["id"], order_id=order_a,
        previous_status="Unfulfilled", new_status="Processing", reason="start",
        actor_id=None, actor_name=None, actor_email=None,
    )
    h2 = _create_order_status_history(
        pg_api_session_factory, store_id=store_a["id"], order_id=order_a,
        previous_status="Processing", new_status="Shipped", reason="ship",
        actor_id=None, actor_name="Actor", actor_email="actor@example.com",
    )
    h3 = _create_order_status_history(
        pg_api_session_factory, store_id=store_a["id"], order_id=order_a,
        previous_status="Shipped", new_status="Delivered", reason="deliver",
        actor_id=None, actor_name="Actor2", actor_email="actor2@example.com",
    )
    _set_created_at(pg_api_session_factory, OrderStatusHistory, h1, t1)
    _set_created_at(pg_api_session_factory, OrderStatusHistory, h2, t2)
    _set_created_at(pg_api_session_factory, OrderStatusHistory, h3, t2)  # tie -> id ASC

    # Store B nested records must never leak into Store A detail
    _create_order_item(
        pg_api_session_factory, store_id=store_b["id"], order_id=order_b,
        product_name="B Item", quantity=1, unit_price=Decimal("7.00"), line_total=Decimal("7.00"),
    )
    _create_order_status_history(
        pg_api_session_factory, store_id=store_b["id"], order_id=order_b,
        previous_status="Unfulfilled", new_status="Processing", reason="B",
    )

    headers = auth_headers(user_a["id"])

    resp = pg_api_client.get(_detail_url(store_a["id"], order_a), headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert set(detail.keys()) == ORDER_DETAIL_KEYS
    _assert_order_summary_contract({k: v for k, v in detail.items() if k in ORDER_SUMMARY_KEYS}, store_a["id"])
    assert detail["id"] == order_a
    assert detail["cart_id"] is None
    assert detail["ship_line1"] == "Line 1"
    assert detail["ship_line2"] is None
    assert detail["ship_city"] == "Metropolis"
    assert detail["ship_state"] is None
    assert detail["ship_postal_code"] == "99999"
    assert detail["ship_country"] == "US"
    assert detail["notes"] is None
    assert detail["subtotal"] == "20.00"
    assert detail["shipping_cost"] == "3.00"
    assert detail["discount"] == "1.00"
    assert detail["total"] == "22.00"

    items = detail["items"]
    assert len(items) == 3
    item_ids = [it["id"] for it in items]
    # Nested items ordering: created_at ASC primary, id ASC tie-breaker (independently exercised)
    assert item_ids[0] == i1
    assert set(item_ids[1:]) == {i2, i3}
    assert item_ids[1] < item_ids[2]
    for it in items:
        _assert_order_item_contract(it, store_a["id"], order_a)
    assert items[0]["unit_price"] == "5.00" and items[0]["line_total"] == "5.00"
    assert items[0]["product_sku"] is None
    # Equal-timestamp tie group (i2,i3): expected sequence derived from seeded items' actual UUID order (id ASC)
    sku_by_item_id = {i2: "SKU-2", i3: "SKU-3"}
    expected_tie_item_ids = sorted([i2, i3], key=lambda item_id: uuid.UUID(item_id))
    assert item_ids[1:] == expected_tie_item_ids
    assert [it["product_sku"] for it in items[1:]] == [sku_by_item_id[i] for i in expected_tie_item_ids]

    history = detail["status_history"]
    assert len(history) == 3
    hist_ids = [h["id"] for h in history]
    # Nested status-history ordering: created_at ASC primary, id ASC tie-breaker (independently exercised)
    assert hist_ids[0] == h1
    assert set(hist_ids[1:]) == {h2, h3}
    assert hist_ids[1] < hist_ids[2]
    for h in history:
        _assert_order_history_contract(h, store_a["id"], order_a)
    assert history[0]["actor_id"] is None and history[0]["actor_name"] is None and history[0]["actor_email"] is None

    # Ownership/scoping: nested records belong only to requested store/order
    assert all(it["store_id"] == store_a["id"] and it["order_id"] == order_a for it in items)
    assert all(h["store_id"] == store_a["id"] and h["order_id"] == order_a for h in history)

    # Empty nested arrays for order with no items/history
    resp_empty = pg_api_client.get(_detail_url(store_a["id"], empty_order_a), headers=headers)
    assert resp_empty.status_code == 200
    empty_detail = resp_empty.json()
    assert set(empty_detail.keys()) == ORDER_DETAIL_KEYS
    assert empty_detail["items"] == []
    assert empty_detail["status_history"] == []


def test_order_detail_nonexistent_and_foreign_store_404(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="ord-404-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="ord-404-b.example.com", name="Store B", owner="Owner B")

    order_b = _create_order(
        pg_api_session_factory,
        store_id=store_b["id"],
        order_number="ORD-999999",
        subtotal=Decimal("1.00"),
        shipping_cost=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("1.00"),
    )
    headers = auth_headers(user_a["id"])

    missing_id = str(uuid.uuid4())
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], missing_id), headers=headers))
    # Foreign-store order requested through authorized Store A path => 404 (not 403)
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], order_b), headers=headers))


def test_orders_authorization_and_authentication(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="ord-authz-a.example.com")
    nonmember = create_staff(pg_api_session_factory, email="nonmember-ord@example.com", global_role="viewer")
    order_a = _create_order(pg_api_session_factory, store_id=store_a["id"], order_number="ORD-000001")

    # Authorized member access
    ok_list = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert ok_list.status_code == 200
    assert ok_list.json()["total"] == 1
    ok_detail = pg_api_client.get(_detail_url(store_a["id"], order_a), headers=auth_headers(user_a["id"]))
    assert ok_detail.status_code == 200

    # Authenticated non-member => 403 (generic)
    assert_generic_403(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(nonmember["id"])))
    assert_generic_403(pg_api_client.get(_detail_url(store_a["id"], order_a), headers=auth_headers(nonmember["id"])))

    # Missing and invalid bearer tokens => generic 401
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"])))
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers_for_token("not-a-jwt")))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], order_a)))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], order_a), headers=auth_headers_for_token("not-a-jwt")))
