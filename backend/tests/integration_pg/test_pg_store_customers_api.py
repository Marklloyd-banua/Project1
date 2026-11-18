"""B1.6 Step 2 (batch 10): PostgreSQL-backed HTTP API integration tests for store customers.

Covers (per approved corrected plan and actual endpoint/schema contracts):
- Customer list envelope, exact response schema (keys/types/nullability, UUID/datetime serialization);
  no monetary Decimal fields in this schema
- Store A list results and totals exclude Store B customers
- Pagination defaults, custom pages, invalid parameters (422), and out-of-range behavior (200 empty + accurate total)
- Actual list ordering with independently exercised primary sort and tie-breaker (created_at DESC, id DESC)
- Detail behavior: existing 200, nonexistent 404, foreign-store customer via authorized Store A path 404 (not 403)
- Exact detail and nested address schema, types, nullability, ownership, and store/customer scoping
  (nested addresses included by actual endpoint)
- Nested collection ordering and tie-breakers for addresses:
  is_default DESC (primary), created_at ASC (secondary), id ASC (tertiary), independently exercised
- AuthN/AuthZ: authorized member, nonmember 403, missing/invalid bearer 401 with generic semantics
- PostgreSQL-compatible seed data, foreign keys, constraints, snapshots, and fixture-cleanup-compatible setup

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import get_settings
from app.models.customer import Customer, CustomerAddress

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
    "AUTH_JWT_SECRET": "b16-customers-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.customers.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-customers-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

CUSTOMER_SUMMARY_KEYS = {
    "id",
    "store_id",
    "email",
    "full_name",
    "phone",
    "status",
    "created_at",
    "updated_at",
}
CUSTOMER_DETAIL_KEYS = CUSTOMER_SUMMARY_KEYS | {"addresses"}
CUSTOMER_ADDRESS_KEYS = {
    "id",
    "store_id",
    "customer_id",
    "label",
    "line1",
    "line2",
    "city",
    "state",
    "postal_code",
    "country",
    "is_default",
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
    return f"/api/v1/stores/{store_id}/customers"


def _detail_url(store_id: str, customer_id: str) -> str:
    return f"/api/v1/stores/{store_id}/customers/{customer_id}"


def _setup_store_a_member(sf, *, domain: str = "cust-a.example.com"):
    user = create_staff(sf, email=f"member-{domain}", global_role="viewer")
    store = create_store(sf, domain=domain, name="Store A", owner="Owner A")
    create_store_membership(sf, store_id=store["id"], staff_user_id=user["id"], role="viewer")
    return user, store


def _create_customer(
    sf,
    *,
    store_id: str,
    email: str,
    full_name: str = "Customer Name",
    phone: str | None = None,
    status: str = "Active",
) -> str:
    with sf() as db:
        row = Customer(
            store_id=uuid.UUID(store_id),
            email=email,
            full_name=full_name,
            phone=phone,
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_address(
    sf,
    *,
    store_id: str,
    customer_id: str,
    label: str | None = None,
    line1: str = "123 Main",
    line2: str | None = None,
    city: str = "City",
    state: str | None = None,
    postal_code: str = "12345",
    country: str = "US",
    is_default: bool = False,
) -> str:
    with sf() as db:
        row = CustomerAddress(
            store_id=uuid.UUID(store_id),
            customer_id=uuid.UUID(customer_id),
            label=label,
            line1=line1,
            line2=line2,
            city=city,
            state=state,
            postal_code=postal_code,
            country=country,
            is_default=is_default,
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


def _assert_customer_summary_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == CUSTOMER_SUMMARY_KEYS
    assert item["store_id"] == expected_store_id
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["email"], str)
    assert isinstance(item["full_name"], str)
    assert item["phone"] is None or isinstance(item["phone"], str)
    assert isinstance(item["status"], str)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])


def _assert_address_contract(item: dict, expected_store_id: str, expected_customer_id: str) -> None:
    assert set(item.keys()) == CUSTOMER_ADDRESS_KEYS
    assert item["store_id"] == expected_store_id
    assert item["customer_id"] == expected_customer_id
    assert isinstance(item["id"], str) and item["id"]
    assert item["label"] is None or isinstance(item["label"], str)
    assert isinstance(item["line1"], str)
    assert item["line2"] is None or isinstance(item["line2"], str)
    assert isinstance(item["city"], str)
    assert item["state"] is None or isinstance(item["state"], str)
    assert isinstance(item["postal_code"], str)
    assert isinstance(item["country"], str)
    assert isinstance(item["is_default"], bool)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    uuid.UUID(item["customer_id"])


def test_customers_list_envelope_schema_scoping_totals_and_serialization(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cust-list-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cust-list-b.example.com", name="Store B", owner="Owner B")

    cust_a = _create_customer(
        pg_api_session_factory,
        store_id=store_a["id"],
        email="alice@example.com",
        full_name="Alice A",
        phone=None,
        status="Suspended",
    )
    _create_customer(
        pg_api_session_factory,
        store_id=store_b["id"],
        email="bob@example.com",
        full_name="Bob B",
        phone="+1999",
        status="Active",
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
    _assert_customer_summary_contract(item, store_a["id"])
    assert item["id"] == cust_a
    assert item["email"] == "alice@example.com"
    assert item["full_name"] == "Alice A"
    assert item["phone"] is None
    assert item["status"] == "Suspended"
    # No monetary Decimal fields exist in this schema/contract.
    assert all(it["store_id"] == store_a["id"] for it in body["items"])


def test_customers_list_pagination_defaults_custom_invalid_and_out_of_range(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cust-page-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cust-page-b.example.com", name="Store B", owner="Owner B")

    for i in range(25):
        _create_customer(pg_api_session_factory, store_id=store_a["id"], email=f"a{i:02d}@example.com")
    for i in range(5):
        _create_customer(pg_api_session_factory, store_id=store_b["id"], email=f"b{i:02d}@example.com")

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


def test_customers_list_deterministic_ordering_created_at_desc_then_id_desc(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cust-order.example.com")

    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # older
    t2 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)  # newer

    c1 = _create_customer(pg_api_session_factory, store_id=store_a["id"], email="c1@example.com")
    c2 = _create_customer(pg_api_session_factory, store_id=store_a["id"], email="c2@example.com")
    c3 = _create_customer(pg_api_session_factory, store_id=store_a["id"], email="c3@example.com")

    _set_created_at(pg_api_session_factory, Customer, c1, t1)
    _set_created_at(pg_api_session_factory, Customer, c2, t2)
    _set_created_at(pg_api_session_factory, Customer, c3, t2)  # tie on created_at -> id DESC

    resp = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]

    # Primary: different created_at values -> created_at DESC (t2 group before t1)
    assert ids[-1] == c1
    assert set(ids[:2]) == {c2, c3}
    # Tie-breaker: equal created_at -> id DESC (independently exercised within t2 group)
    assert ids[0] > ids[1]


def test_customer_detail_existing_nonexistent_and_foreign_store_404(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cust-detail-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cust-detail-b.example.com", name="Store B", owner="Owner B")

    cust_a = _create_customer(
        pg_api_session_factory,
        store_id=store_a["id"],
        email="detail@example.com",
        full_name="Detail Cust",
        phone="+1555",
        status="Active",
    )
    cust_b = _create_customer(
        pg_api_session_factory,
        store_id=store_b["id"],
        email="foreign@example.com",
        full_name="Foreign Cust",
    )

    headers = auth_headers(user_a["id"])

    resp_ok = pg_api_client.get(_detail_url(store_a["id"], cust_a), headers=headers)
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert set(body.keys()) == CUSTOMER_DETAIL_KEYS
    _assert_customer_summary_contract({k: v for k, v in body.items() if k != "addresses"}, store_a["id"])
    assert body["id"] == cust_a
    assert body["email"] == "detail@example.com"
    assert body["phone"] == "+1555"
    assert body["addresses"] == []

    missing_id = str(uuid.uuid4())
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], missing_id), headers=headers))

    # Foreign-store customer requested through authorized Store A path => 404 (not 403)
    assert_generic_404(pg_api_client.get(_detail_url(store_a["id"], cust_b), headers=headers))


def test_customer_detail_nested_addresses_schema_scoping_and_ordering(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cust-addr-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="cust-addr-b.example.com", name="Store B", owner="Owner B")

    cust_a1 = _create_customer(pg_api_session_factory, store_id=store_a["id"], email="a1@example.com")
    cust_a2 = _create_customer(pg_api_session_factory, store_id=store_a["id"], email="a2@example.com")
    cust_b = _create_customer(pg_api_session_factory, store_id=store_b["id"], email="b@example.com")

    # Address ordering (actual): is_default DESC, created_at ASC, id ASC
    # - a_def: sole default remains first even though a_nd1 has earlier created_at
    #   -> primary is_default DESC exercised independently of created_at ASC
    # - a_nd1 vs (a_nd2,a_nd3): same is_default=False, different created_at -> secondary created_at ASC exercised
    # - a_nd2 vs a_nd3: same is_default=False and same created_at -> tertiary id ASC exercised
    a_def = _create_address(
        pg_api_session_factory, store_id=store_a["id"], customer_id=cust_a1,
        label="Home", line1="1 Default", line2=None, city="Town", state=None,
        postal_code="10000", country="US", is_default=True,
    )
    a_nd1 = _create_address(
        pg_api_session_factory, store_id=store_a["id"], customer_id=cust_a1,
        label=None, line1="2 NonDefault Early", line2="Apt 1", city="Town", state="TS",
        postal_code="10001", country="US", is_default=False,
    )
    a_nd2 = _create_address(
        pg_api_session_factory, store_id=store_a["id"], customer_id=cust_a1,
        label="Office", line1="3 NonDefault Tie", line2=None, city="Town", state=None,
        postal_code="10002", country="US", is_default=False,
    )
    a_nd3 = _create_address(
        pg_api_session_factory, store_id=store_a["id"], customer_id=cust_a1,
        label="Other", line1="4 NonDefault Tie", line2=None, city="Town", state=None,
        postal_code="10003", country="US", is_default=False,
    )

    t_nd_early = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # earliest overall (non-default)
    t_default = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)   # later than a_nd1, earlier than tie pair
    t_nd_tie = datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc)
    _set_created_at(pg_api_session_factory, CustomerAddress, a_nd1, t_nd_early)
    _set_created_at(pg_api_session_factory, CustomerAddress, a_def, t_default)
    _set_created_at(pg_api_session_factory, CustomerAddress, a_nd2, t_nd_tie)
    _set_created_at(pg_api_session_factory, CustomerAddress, a_nd3, t_nd_tie)

    # Addresses for other customer in same store and for other store must never leak.
    a_other_customer_same_store = _create_address(
        pg_api_session_factory, store_id=store_a["id"], customer_id=cust_a2,
        line1="Other Customer", is_default=False,
    )
    a_other_store = _create_address(
        pg_api_session_factory, store_id=store_b["id"], customer_id=cust_b,
        line1="Other Store", is_default=False,
    )

    resp = pg_api_client.get(_detail_url(store_a["id"], cust_a1), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    detail = resp.json()
    assert set(detail.keys()) == CUSTOMER_DETAIL_KEYS

    addresses = detail["addresses"]
    ids = [a["id"] for a in addresses]
    # Primary (is_default DESC) proven independently: default appears before every non-default
    # even though a_nd1 has an earlier created_at than the default.
    assert ids[0] == a_def
    assert all(addr["id"] == a_def or addr["is_default"] is False for addr in addresses)
    assert addresses[0]["is_default"] is True
    # Secondary (created_at ASC) among non-defaults: a_nd1 before the later tied pair.
    assert ids[1] == a_nd1
    assert set(ids[2:]) == {a_nd2, a_nd3}
    # Tertiary (id ASC) for equal is_default/created_at pair.
    assert ids[2] < ids[3]

    assert ids == [a_def, a_nd1] + sorted([a_nd2, a_nd3])
    assert a_other_customer_same_store not in ids
    assert a_other_store not in ids

    for addr in addresses:
        _assert_address_contract(addr, store_a["id"], cust_a1)

    # Spot-check nullability/types on representative records
    assert addresses[0]["is_default"] is True
    assert addresses[0]["label"] == "Home"
    assert addresses[0]["line2"] is None
    assert addresses[0]["state"] is None
    assert addresses[1]["label"] is None
    assert addresses[1]["line2"] == "Apt 1"
    assert addresses[1]["state"] == "TS"


def test_customers_authorization_and_authentication(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="cust-authz-a.example.com")
    nonmember = create_staff(pg_api_session_factory, email="nonmember-cust@example.com", global_role="viewer")
    cust_a = _create_customer(pg_api_session_factory, store_id=store_a["id"], email="authz@example.com")

    # Authorized member access
    ok_list = pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert ok_list.status_code == 200
    assert ok_list.json()["total"] == 1
    ok_detail = pg_api_client.get(_detail_url(store_a["id"], cust_a), headers=auth_headers(user_a["id"]))
    assert ok_detail.status_code == 200

    # Authenticated non-member => 403 (generic)
    assert_generic_403(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers(nonmember["id"])))
    assert_generic_403(pg_api_client.get(_detail_url(store_a["id"], cust_a), headers=auth_headers(nonmember["id"])))

    # Missing and invalid bearer tokens => generic 401
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"])))
    assert_generic_401(pg_api_client.get(_list_url(store_a["id"]), headers=auth_headers_for_token("not-a-jwt")))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], cust_a)))
    assert_generic_401(pg_api_client.get(_detail_url(store_a["id"], cust_a), headers=auth_headers_for_token("not-a-jwt")))
