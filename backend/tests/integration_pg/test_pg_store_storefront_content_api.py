"""B1.6 Step 2 (batch 11): PostgreSQL-backed HTTP API integration tests for storefront content.

Covers (per approved corrected plan and actual endpoint/schema contracts):
- Slides list: exact response envelope and schema, field names/types/nullability,
  UUID/datetime serialization, Store A excludes Store B records/totals, actual
  deterministic ordering (position ASC, id ASC; position primary independently exercised;
  positions are unique per store so equal-position id tie-break is not constraint-applicable)
- Sections list: exact response envelope/schema, field types/nullability, UUID/datetime
  serialization (including JSON/JSONB config as stored), store isolation and accurate totals,
  actual deterministic ordering (position ASC, id ASC; primary independently exercised)
- Footer links list: exact response envelope/schema, field types/nullability, UUID/datetime
  serialization, store isolation and accurate totals, actual deterministic ordering
  (position ASC, id ASC; primary independently exercised)
- Pagination defaults, custom pages, invalid parameters (422), and out-of-range behavior
  (200 empty + accurate total)
- AuthN/AuthZ: authorized store member can read all three collections; authenticated
  nonmember generic 403; missing and invalid/malformed bearer generic 401 with bearer challenge
- PostgreSQL-compatible seed data, foreign keys, constraints, and fixture-cleanup-compatible setup

Uses existing verified B1.6 disposable PostgreSQL fixture and helpers without modification.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from app.core.config import get_settings
from app.models.storefront import StorefrontFooterLink, StorefrontSection, StorefrontSlide

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
    "AUTH_JWT_SECRET": "b16-storefront-content-test-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://b16.storefront-content.test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-b16-storefront-content-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
}

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
SECTION_KEYS = {
    "id",
    "store_id",
    "section_type",
    "title",
    "subtitle",
    "position",
    "is_active",
    "config",
    "created_at",
    "updated_at",
}
FOOTER_LINK_KEYS = {"id", "store_id", "label", "url", "position", "created_at", "updated_at"}

ENVELOPE_KEYS = {"items", "total", "page", "page_size"}


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


def _slides_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/slides"


def _sections_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/sections"


def _footer_links_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/storefront/footer-links"


def _setup_store_a_member(sf, *, domain: str = "sf-a.example.com"):
    user = create_staff(sf, email=f"member-{domain}", global_role="viewer")
    store = create_store(sf, domain=domain, name="Store A", owner="Owner A")
    create_store_membership(sf, store_id=store["id"], staff_user_id=user["id"], role="viewer")
    return user, store


def _create_slide(
    sf,
    *,
    store_id: str,
    title: str = "Slide",
    subtitle: str | None = None,
    image_url: str = "https://example.com/slide.png",
    cta_url: str | None = None,
    cta_label: str | None = None,
    position: int = 1,
    target_category_id: str | None = None,
    is_active: bool = True,
) -> str:
    with sf() as db:
        row = StorefrontSlide(
            store_id=uuid.UUID(store_id),
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            cta_url=cta_url,
            cta_label=cta_label,
            position=position,
            target_category_id=uuid.UUID(target_category_id) if target_category_id else None,
            is_active=is_active,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_section(
    sf,
    *,
    store_id: str,
    section_type: str = "banner",
    title: str = "Section",
    subtitle: str | None = None,
    position: int = 1,
    is_active: bool = True,
    config: Any | None = None,
) -> str:
    with sf() as db:
        row = StorefrontSection(
            store_id=uuid.UUID(store_id),
            section_type=section_type,
            title=title,
            subtitle=subtitle,
            position=position,
            is_active=is_active,
            config=config,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _create_footer_link(
    sf,
    *,
    store_id: str,
    label: str = "Link",
    url: str = "https://example.com",
    position: int = 1,
) -> str:
    with sf() as db:
        row = StorefrontFooterLink(
            store_id=uuid.UUID(store_id),
            label=label,
            url=url,
            position=position,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _assert_slide_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == SLIDE_KEYS
    assert item["store_id"] == expected_store_id
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    assert isinstance(item["title"], str)
    assert item["subtitle"] is None or isinstance(item["subtitle"], str)
    assert isinstance(item["image_url"], str)
    assert item["cta_url"] is None or isinstance(item["cta_url"], str)
    assert item["cta_label"] is None or isinstance(item["cta_label"], str)
    assert isinstance(item["position"], int)
    if item["target_category_id"] is None:
        assert item["target_category_id"] is None
    else:
        assert isinstance(item["target_category_id"], str)
        uuid.UUID(item["target_category_id"])
    assert isinstance(item["is_active"], bool)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]


def _assert_section_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == SECTION_KEYS
    assert item["store_id"] == expected_store_id
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    assert isinstance(item["section_type"], str)
    assert isinstance(item["title"], str)
    assert item["subtitle"] is None or isinstance(item["subtitle"], str)
    assert isinstance(item["position"], int)
    assert isinstance(item["is_active"], bool)
    # config is Any | None (JSON/JSONB, API-validated only); assert presence/type shape loosely
    assert "config" in item
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]


def _assert_footer_link_contract(item: dict, expected_store_id: str) -> None:
    assert set(item.keys()) == FOOTER_LINK_KEYS
    assert item["store_id"] == expected_store_id
    uuid.UUID(item["id"])
    uuid.UUID(item["store_id"])
    assert isinstance(item["label"], str)
    assert isinstance(item["url"], str)
    assert isinstance(item["position"], int)
    assert isinstance(item["created_at"], str) and item["created_at"]
    assert isinstance(item["updated_at"], str) and item["updated_at"]


def test_slides_list_envelope_schema_scoping_totals_and_serialization(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="slides-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="slides-b.example.com", name="Store B", owner="Owner B")

    slide_a1 = _create_slide(
        pg_api_session_factory,
        store_id=store_a["id"],
        title="Slide A1",
        subtitle=None,
        image_url="https://example.com/a1.png",
        cta_url=None,
        cta_label=None,
        position=1,
        target_category_id=None,
        is_active=False,
    )
    slide_a2 = _create_slide(
        pg_api_session_factory,
        store_id=store_a["id"],
        title="Slide A2",
        subtitle="Sub A2",
        image_url="http://example.com/a2.png",
        cta_url="https://example.com/cta",
        cta_label="Shop",
        position=2,
        target_category_id=None,
        is_active=True,
    )
    _create_slide(
        pg_api_session_factory,
        store_id=store_b["id"],
        title="Slide B",
        subtitle="Sub B",
        image_url="https://example.com/b.png",
        position=1,
        is_active=True,
    )

    resp = pg_api_client.get(_slides_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(item["store_id"] == store_a["id"] for item in body["items"])

    # Actual deterministic ordering: position ASC, id ASC (positions unique per store)
    assert [item["id"] for item in body["items"]] == [slide_a1, slide_a2]
    assert [item["position"] for item in body["items"]] == [1, 2]

    first, second = body["items"]
    _assert_slide_contract(first, store_a["id"])
    _assert_slide_contract(second, store_a["id"])
    assert first["id"] == slide_a1
    assert first["title"] == "Slide A1"
    assert first["subtitle"] is None
    assert first["image_url"] == "https://example.com/a1.png"
    assert first["cta_url"] is None
    assert first["cta_label"] is None
    assert first["target_category_id"] is None
    assert first["is_active"] is False
    assert second["subtitle"] == "Sub A2"
    assert second["cta_url"] == "https://example.com/cta"
    assert second["cta_label"] == "Shop"
    assert second["is_active"] is True


def test_sections_list_envelope_schema_scoping_totals_and_serialization(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="sections-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="sections-b.example.com", name="Store B", owner="Owner B")

    sec_a1 = _create_section(
        pg_api_session_factory,
        store_id=store_a["id"],
        section_type="custom_text",
        title="Section A1",
        subtitle=None,
        position=1,
        is_active=False,
        config=None,
    )
    sec_a2 = _create_section(
        pg_api_session_factory,
        store_id=store_a["id"],
        section_type="banner",
        title="Section A2",
        subtitle="Sub A2",
        position=2,
        is_active=True,
        config={"nested": {"a": [1, 2, {"x": True}], "b": None}, "ids": ["x", "y"]},
    )
    sec_a3 = _create_section(
        pg_api_session_factory,
        store_id=store_a["id"],
        section_type="featured_products",
        title="Section A3",
        subtitle=None,
        position=3,
        is_active=True,
        config=[{"kind": "banner"}, {"text": "hello"}],
    )
    _create_section(
        pg_api_session_factory,
        store_id=store_b["id"],
        section_type="banner",
        title="Section B",
        position=1,
        config={"leak": True},
    )

    resp = pg_api_client.get(_sections_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert all(item["store_id"] == store_a["id"] for item in body["items"])

    # Actual deterministic ordering: position ASC, id ASC (positions unique per store)
    assert [item["id"] for item in body["items"]] == [sec_a1, sec_a2, sec_a3]
    assert [item["position"] for item in body["items"]] == [1, 2, 3]

    items = body["items"]
    for it in items:
        _assert_section_contract(it, store_a["id"])

    assert items[0]["id"] == sec_a1
    assert items[0]["section_type"] == "custom_text"
    assert items[0]["subtitle"] is None
    assert items[0]["is_active"] is False
    assert items[0]["config"] is None

    assert items[1]["id"] == sec_a2
    assert items[1]["section_type"] == "banner"
    assert items[1]["subtitle"] == "Sub A2"
    assert items[1]["is_active"] is True
    assert items[1]["config"] == {"nested": {"a": [1, 2, {"x": True}], "b": None}, "ids": ["x", "y"]}

    assert items[2]["id"] == sec_a3
    assert items[2]["section_type"] == "featured_products"
    assert items[2]["config"] == [{"kind": "banner"}, {"text": "hello"}]


def test_footer_links_list_envelope_schema_scoping_totals_and_serialization(
    pg_api_client, pg_api_session_factory
):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="footer-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="footer-b.example.com", name="Store B", owner="Owner B")

    fl_a1 = _create_footer_link(
        pg_api_session_factory,
        store_id=store_a["id"],
        label="About",
        url="https://example.com/about",
        position=1,
    )
    fl_a2 = _create_footer_link(
        pg_api_session_factory,
        store_id=store_a["id"],
        label="Contact",
        url="http://example.com/contact",
        position=2,
    )
    _create_footer_link(
        pg_api_session_factory,
        store_id=store_b["id"],
        label="Other",
        url="https://example.com/other",
        position=1,
    )

    resp = pg_api_client.get(_footer_links_url(store_a["id"]), headers=auth_headers(user_a["id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(item["store_id"] == store_a["id"] for item in body["items"])

    # Actual deterministic ordering: position ASC, id ASC (positions unique per store)
    assert [item["id"] for item in body["items"]] == [fl_a1, fl_a2]
    assert [item["position"] for item in body["items"]] == [1, 2]

    first, second = body["items"]
    _assert_footer_link_contract(first, store_a["id"])
    _assert_footer_link_contract(second, store_a["id"])
    assert first["id"] == fl_a1
    assert first["label"] == "About"
    assert first["url"] == "https://example.com/about"
    assert second["id"] == fl_a2
    assert second["label"] == "Contact"
    assert second["url"] == "http://example.com/contact"


def test_storefront_content_pagination_defaults_custom_invalid_and_out_of_range(
    pg_api_client, pg_api_session_factory
):
    # Sections allow >20 rows (position >= 1 unique) and exercise shared pagination behavior.
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="sf-page-a.example.com")
    store_b = create_store(pg_api_session_factory, domain="sf-page-b.example.com", name="Store B", owner="Owner B")

    for pos in range(1, 26):
        _create_section(pg_api_session_factory, store_id=store_a["id"], position=pos, title=f"S{pos}")
    for pos in range(1, 6):
        _create_section(pg_api_session_factory, store_id=store_b["id"], position=pos, title=f"B{pos}")

    headers = auth_headers(user_a["id"])

    resp_default = pg_api_client.get(_sections_url(store_a["id"]), headers=headers)
    assert resp_default.status_code == 200
    body_default = resp_default.json()
    assert set(body_default.keys()) == ENVELOPE_KEYS
    assert body_default["page"] == 1
    assert body_default["page_size"] == 20
    assert body_default["total"] == 25
    assert len(body_default["items"]) == 20
    assert all(it["store_id"] == store_a["id"] for it in body_default["items"])

    resp_custom = pg_api_client.get(
        f"{_sections_url(store_a['id'])}?page=2&page_size=10",
        headers=headers,
    )
    assert resp_custom.status_code == 200
    body_custom = resp_custom.json()
    assert body_custom["page"] == 2
    assert body_custom["page_size"] == 10
    assert body_custom["total"] == 25
    assert len(body_custom["items"]) == 10
    assert all(it["store_id"] == store_a["id"] for it in body_custom["items"])

    resp_oor = pg_api_client.get(
        f"{_sections_url(store_a['id'])}?page=5&page_size=20",
        headers=headers,
    )
    assert resp_oor.status_code == 200
    assert resp_oor.json() == {"items": [], "total": 25, "page": 5, "page_size": 20}

    for qs in ("?page=0", "?page_size=0", "?page_size=101"):
        resp_invalid = pg_api_client.get(f"{_sections_url(store_a['id'])}{qs}", headers=headers)
        assert resp_invalid.status_code == 422, qs


def test_storefront_content_deterministic_ordering_position_asc(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="sf-order.example.com")

    # Slides: positions 1..4 unique per store; insert out of order to exercise primary position ASC.
    s3 = _create_slide(pg_api_session_factory, store_id=store_a["id"], position=3, title="P3")
    s1 = _create_slide(pg_api_session_factory, store_id=store_a["id"], position=1, title="P1")
    s4 = _create_slide(pg_api_session_factory, store_id=store_a["id"], position=4, title="P4")
    s2 = _create_slide(pg_api_session_factory, store_id=store_a["id"], position=2, title="P2")

    # Sections/footer links: positions >=1 unique per store; insert out of order.
    sec3 = _create_section(pg_api_session_factory, store_id=store_a["id"], position=3, title="Sec3")
    sec1 = _create_section(pg_api_session_factory, store_id=store_a["id"], position=1, title="Sec1")
    sec2 = _create_section(pg_api_session_factory, store_id=store_a["id"], position=2, title="Sec2")

    fl2 = _create_footer_link(pg_api_session_factory, store_id=store_a["id"], position=2, label="B")
    fl3 = _create_footer_link(pg_api_session_factory, store_id=store_a["id"], position=3, label="C")
    fl1 = _create_footer_link(pg_api_session_factory, store_id=store_a["id"], position=1, label="A")

    headers = auth_headers(user_a["id"])

    resp_slides = pg_api_client.get(_slides_url(store_a["id"]), headers=headers)
    assert resp_slides.status_code == 200
    slide_items = resp_slides.json()["items"]
    assert [i["id"] for i in slide_items] == [s1, s2, s3, s4]
    assert [i["position"] for i in slide_items] == [1, 2, 3, 4]

    resp_sec = pg_api_client.get(_sections_url(store_a["id"]), headers=headers)
    assert resp_sec.status_code == 200
    sec_items = resp_sec.json()["items"]
    assert [i["id"] for i in sec_items] == [sec1, sec2, sec3]
    assert [i["position"] for i in sec_items] == [1, 2, 3]

    resp_fl = pg_api_client.get(_footer_links_url(store_a["id"]), headers=headers)
    assert resp_fl.status_code == 200
    fl_items = resp_fl.json()["items"]
    assert [i["id"] for i in fl_items] == [fl1, fl2, fl3]
    assert [i["position"] for i in fl_items] == [1, 2, 3]


def test_storefront_content_authentication_and_authorization(pg_api_client, pg_api_session_factory):
    user_a, store_a = _setup_store_a_member(pg_api_session_factory, domain="sf-authz-a.example.com")
    nonmember = create_staff(pg_api_session_factory, email="nonmember-sf@example.com", global_role="viewer")

    _create_slide(pg_api_session_factory, store_id=store_a["id"], position=1)
    _create_section(pg_api_session_factory, store_id=store_a["id"], position=1)
    _create_footer_link(pg_api_session_factory, store_id=store_a["id"], position=1)

    endpoints = [_slides_url(store_a["id"]), _sections_url(store_a["id"]), _footer_links_url(store_a["id"])]

    # Authorized store member can read all three collections
    for url in endpoints:
        resp = pg_api_client.get(url, headers=auth_headers(user_a["id"]))
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == ENVELOPE_KEYS
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["store_id"] == store_a["id"]

    # Authenticated non-member => generic 403 on all three
    for url in endpoints:
        assert_generic_403(pg_api_client.get(url, headers=auth_headers(nonmember["id"])))

    # Missing and invalid/malformed bearer tokens => generic 401 with bearer challenge on all three
    for url in endpoints:
        assert_generic_401(pg_api_client.get(url))
        assert_generic_401(pg_api_client.get(url, headers=auth_headers_for_token("not-a-jwt")))
