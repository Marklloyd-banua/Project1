"""B1.6 Step 2 (batch 8): PostgreSQL-backed HTTP API integration tests for store inventory adjustments.

Covers (per approved corrected plan and actual endpoint/schema contracts):
- List envelope, exact response keys/types, nullable values, UUID/datetime serialization
  (no monetary Decimal fields in this schema)
- Store scoping: Store A results/totals exclude Store B records
- Pagination defaults, custom pages, invalid parameters (422), and out-of-range behavior (200 empty + correct total)
- Actual endpoint ordering including tie-break behavior where valid constraints permit
  (occurred_at desc, created_at desc, id desc)
- Detail endpoint: existing record 200, nonexistent 404, foreign-store record via authorized Store A path 404 (not 403)
- AuthN/AuthZ: authorized member access, nonmember 403, missing/invalid bearer 401 with generic semantics
- PostgreSQL-compatible seed data, foreign keys, constraints, and fixture-cleanup-compatible setup

Focused on inventory-adjustment API behavior. Uses existing verified B1.6 disposable PostgreSQL fixture and helpers.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.product import Product

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
    "AUTH_JWT_SECRET": "b16-inv-adj-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.invadj.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-invadj-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

ADJUSTMENT_KEYS = {
    "id",
    "store_id",
    "product_id",
    "product_name",
    "sku",
    "adjustment_amount",
    "previous_quantity",
    "new_quantity",
    "reason",
    "actor_id",
    "actor_name",
    "actor_email",
    "occurred_at",
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
    return f"/api/v1/stores/{store_id}/inventory-adjustments"


def _detail_url(store_id: str, adjustment_id: str) -> str:
    return f"/api/v1/stores/{store_id}/inventory-adjustments/{adjustment_id}"


def _setup_store_a_member(sf, *, domain: str = "inv-a.example.com"):
    user = create_staff(sf, email=f"member-{domain}", global_role="viewer")
    store = create_store(sf, domain=domain, name="Store A", owner="Owner A")
    create_store_membership(sf, store_id=store["id"], staff_user_id=user["id"], role="viewer")
    return user, store


def _create_product(
    sf,
    *,
    store_id: str,
    name: str = "Prod",
    slug: str = "prod",
    status: str = "Active",
) -> str:
    with sf() as db:
        row = Product(
            store_id=uuid.UUID(store_id),
            name=name,
            slug=slug,
            status=status,
            price=Decimal("10.00"),
            description="",
            image="https://example.com/p.png",
            stock_quantity=0,
            low_stock_threshold=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_adjustment(
    sf,
    *,
    store_id: str,
    product_id: str,
    adjustment_amount: int,
    previous_quantity: int,
    new_quantity: int,
    reason: str = "Manual count",
    product_name: str | None = "Prod Snapshot",
    sku: str | None = "SKU-1",
    actor_id: str | None = None,
    actor_name: str | None = "Actor Name",
    actor_email: str | None = "actor@example.com",
    occurred_at: datetime | None = None,
) -> str:
    with sf() as db:
        row = InventoryAdjustment(
            store_id=uuid.UUID(store_id),
            product_id=uuid.UUID(product_id),
            adjustment_amount=adjustment_amount,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            reason=reason,
            product_name=product_name,
            sku=sku,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            actor_name=actor_name,
            actor_email=actor_email,
            occurred_at=occurred_at or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _assert_adjustment_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == ADJUSTMENT_KEYS
    assert item["store_id"] == expected_store_id
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["product_id"], str) and item["product_id"]
    assert item["product_name"] is None or isinstance(item["product_name"], str)
    assert item["sku"] is None or isinstance(item["sku"], str)
    assert isinstance(item["adjustment_amount"], int)
    assert isinstance(item["previous_quantity"], int)
    assert isinstance(item["new_quantity"], int)
    assert isinstance(item["reason"], str)
    assert item["actor_id"] is None or isinstance(item["actor_id"], str)
    assert item["actor_name"] is None or isinstance(item["actor_name"], str)
    assert item["actor_email"] is None or isinstance(item["actor_email"], str)
    assert isinstance(item["occurred_at"], str) and item["occurred_at"]
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    uuid.UUID(item["product_id"])
    if item["actor_id"] is not None:
        uuid.UUID(item["actor_id"])


def test_inventory_adjustments_list_scoped_schema_nullable_and_totals(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="inv-list-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="inv-list-b.example.com", name="Store B", owner="Owner B")
    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A", slug="prod-a")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b["id"], name="Prod B", slug="prod-b")

    adj_a = _create_adjustment(
        pg_api_session_factory,
        store_id=store_a["id"],
        product_id=prod_a,
        adjustment_amount=-2,
        previous_quantity=5,
        new_quantity=3,
        reason="Shrinkage",
        product_name=None,
        sku=None,
        actor_id=None,
        actor_name=None,
        actor_email=None,
        occurred_at=datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    _create_adjustment(
        pg_api_session_factory,
        store_id=store_b["id"],
        product_id=prod_b,
        adjustment_amount=1,
        previous_quantity=0,
        new_quantity=1,
        reason="B only",
        occurred_at=datetime(2026, 2, 2, 10, 0, 0, tzinfo=timezone.utc),
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
    _assert_adjustment_contract(item, store_a["id"])
    assert item["id"] == adj_a
    assert item["product_id"] == prod_a
    assert item["product_name"] is None
    assert item["sku"] is None
    assert item["actor_id"] is None
    assert item["actor_name"] is None
    assert item["actor_email"] is None
    assert item["adjustment_amount"] == -2
    assert item["previous_quantity"] == 5
    assert item["new_quantity"] == 3
    assert item["new_quantity"] == item["previous_quantity"] + item["adjustment_amount"]
    assert all(it["store_id"] == store_a["id"] for it in body["items"])


def test_inventory_adjustments_pagination_defaults_custom_invalid_and_out_of_range(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="inv-page-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="inv-page-b.example.com", name="Store B", owner="Owner B")
    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A", slug="prod-a")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b["id"], name="Prod B", slug="prod-b")

    for i in range(25):
        _create_adjustment(
            pg_api_session_factory,
            store_id=store_a["id"],
            product_id=prod_a,
            adjustment_amount=1,
            previous_quantity=i,
            new_quantity=i + 1,
            reason=f"r-{i}",
            occurred_at=datetime(2026, 1, 1, 0, 0, i if i < 60 else 0, tzinfo=timezone.utc),
        )
    for i in range(5):
        _create_adjustment(
            pg_api_session_factory,
            store_id=store_b["id"],
            product_id=prod_b,
            adjustment_amount=1,
            previous_quantity=i,
            new_quantity=i + 1,
            reason=f"b-{i}",
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


def test_inventory_adjustments_deterministic_ordering_occurred_created_id(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="inv-order.example.com")
    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A", slug="prod-a")

    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # oldest occurred_at
    t2 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)  # middle occurred_at (tie group for id desc)
    t3 = datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc)  # newest occurred_at (tie group for created_at desc)

    # a1: different (oldest) occurred_at -> proves occurred_at DESC places this last overall.
    a1 = _create_adjustment(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a,
        adjustment_amount=1, previous_quantity=0, new_quantity=1, occurred_at=t1,
    )
    # a2,a3: equal occurred_at (t2) with equal created_at -> proves id DESC tie-breaker.
    a2 = _create_adjustment(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a,
        adjustment_amount=1, previous_quantity=1, new_quantity=2, occurred_at=t2,
    )
    a3 = _create_adjustment(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a,
        adjustment_amount=1, previous_quantity=2, new_quantity=3, occurred_at=t2,
    )
    # b1,b2: equal occurred_at (t3) with different created_at -> proves created_at DESC secondary sort.
    b1 = _create_adjustment(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a,
        adjustment_amount=1, previous_quantity=3, new_quantity=4, occurred_at=t3,
    )
    b2 = _create_adjustment(
        pg_api_session_factory, store_id=store_a["id"], product_id=prod_a,
        adjustment_amount=1, previous_quantity=4, new_quantity=5, occurred_at=t3,
    )

    created_tie = datetime(2026, 1, 4, 10, 0, 0, tzinfo=timezone.utc)
    created_newer = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
    created_older = datetime(2026, 1, 5, 11, 0, 0, tzinfo=timezone.utc)

    # Isolate secondary key (created_at DESC) from tertiary (id DESC): assign newer created_at
    # to the member of the b-group with the smaller UUID id so id-desc alone would prefer the other.
    b_pair = [b1, b2]
    b_pair_sorted = sorted(b_pair)  # canonical UUID string order
    newer_created_id = b_pair_sorted[0]
    older_created_id = b_pair_sorted[1]

    with pg_api_session_factory() as db:
        # Equal occurred_at (t2) + equal created_at => id DESC (preserved coverage).
        db.get(InventoryAdjustment, uuid.UUID(a2)).created_at = created_tie
        db.get(InventoryAdjustment, uuid.UUID(a3)).created_at = created_tie
        # Equal occurred_at (t3) + different created_at => created_at DESC regardless of id ordering.
        db.get(InventoryAdjustment, uuid.UUID(newer_created_id)).created_at = created_newer
        db.get(InventoryAdjustment, uuid.UUID(older_created_id)).created_at = created_older
        db.commit()

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = [item["id"] for item in items]
    assert ids == [newer_created_id, older_created_id] + sorted([a2, a3], reverse=True) + [a1]

    by_id = {item["id"]: item for item in items}
    # Different occurred_at values -> occurred_at DESC groups: t3 before t2 before t1.
    assert by_id[newer_created_id]["occurred_at"] > by_id[a2]["occurred_at"] > by_id[a1]["occurred_at"]
    # Equal occurred_at (t3) + different created_at -> newer created_at first (isolated from id DESC).
    assert by_id[newer_created_id]["occurred_at"] == by_id[older_created_id]["occurred_at"]
    assert by_id[newer_created_id]["created_at"] > by_id[older_created_id]["created_at"]
    assert newer_created_id < older_created_id  # would lose if incorrectly ordered by id DESC
    # Equal occurred_at (t2) + equal created_at -> id DESC (preserved coverage).
    assert by_id[a2]["occurred_at"] == by_id[a3]["occurred_at"]
    assert by_id[a2]["created_at"] == by_id[a3]["created_at"]
    assert ids[2:4] == sorted([a2, a3], reverse=True)


def test_inventory_adjustment_detail_existing_nonexistent_and_foreign_store_404(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="inv-detail-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="inv-detail-b.example.com", name="Store B", owner="Owner B")
    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A", slug="prod-a")
    prod_b = _create_product(pg_api_session_factory, store_id=store_b["id"], name="Prod B", slug="prod-b")

    adj_a = _create_adjustment(
        pg_api_session_factory,
        store_id=store_a["id"],
        product_id=prod_a,
        adjustment_amount=3,
        previous_quantity=7,
        new_quantity=10,
        reason="Restock",
        product_name="Prod A Snapshot",
        sku="SKU-A",
        actor_id=None,
        actor_name="Actor",
        actor_email="actor@example.com",
        occurred_at=datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc),
    )
    adj_b = _create_adjustment(
        pg_api_session_factory,
        store_id=store_b["id"],
        product_id=prod_b,
        adjustment_amount=1,
        previous_quantity=0,
        new_quantity=1,
        reason="Foreign",
    )

    headers = auth_headers(user_a["id"])

    resp_ok = pg_api_client.get(_detail_url(store_a["id"], adj_a), headers=headers)
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert set(body.keys()) == ADJUSTMENT_KEYS
    _assert_adjustment_contract(body, store_a["id"])
    assert body["id"] == adj_a
    assert body["product_id"] == prod_a
    assert body["adjustment_amount"] == 3
    assert body["previous_quantity"] == 7
    assert body["new_quantity"] == 10

    missing_id = str(uuid.uuid4())
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], missing_id), headers=headers))

    # Foreign-store record requested through authorized Store A path => 404 (not 403)
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], adj_b), headers=headers))


def test_inventory_adjustments_authorization_and_authentication(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="inv-authz-a.example.com")
    nonmember = create_staff(pg_api_session_factory, email="nonmember-inv@example.com", global_role="viewer")
    prod_a = _create_product(pg_api_session_factory, store_id=store_a["id"], name="Prod A", slug="prod-a")
    adj_a = _create_adjustment(
        pg_api_session_factory,
        store_id=store_a["id"],
        product_id=prod_a,
        adjustment_amount=1,
        previous_quantity=0,
        new_quantity=1,
    )

    # Authorized member access
    ok_list = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert ok_list.status_code == 200
    assert ok_list.json()["total"] == 1
    ok_detail = pg_api_client.get(_detail_url(store_a["id"], adj_a), headers=auth_headers(user_a["id"]))
    assert ok_detail.status_code == 200

    # Authenticated non-member => 403 (generic)
    assert_generic_403(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(nonmember["id"])))
    assert_generic_403(pg_api_client.get(_detail_url(store_a["id"], adj_a), headers=auth_headers(nonmember["id"])))

    # Missing and invalid bearer tokens => generic 401
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"])))
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers_for_token("not-a-jwt")))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], adj_a)))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], adj_a), headers=auth_headers_for_token("not-a-jwt")))
