from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.category import Category
from app.models.product import Product, ProductImage
from app.models.store import Store
from app.models.storefront import StorefrontSlide
from app.services.storefront_hero import (
    assemble_storefront_hero_mapping_read,
    list_storefront_hero_mappings,
)


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with SessionLocal() as session:
        yield session
        session.rollback()
    engine.dispose()


def _make_store(db: Session, domain: str, name: str = "Store") -> Store:
    store = Store(name=name, owner="Owner", domain=domain)
    db.add(store)
    db.flush()
    return store


def _make_category(
    db: Session,
    store: Store,
    *,
    name: str,
    slug: str,
    status: str = "Active",
) -> Category:
    cat = Category(store_id=store.id, name=name, slug=slug, status=status)
    db.add(cat)
    db.flush()
    return cat


def _make_product(
    db: Session,
    store: Store,
    category: Category | None,
    *,
    name: str,
    slug: str,
    status: str = "Active",
    image: str = "",
    stock_quantity: int = 10,
    created_at: datetime | None = None,
) -> Product:
    product = Product(
        store_id=store.id,
        name=name,
        slug=slug,
        description="",
        image=image or "",
        price=10.00,
        stock_quantity=stock_quantity,
        low_stock_threshold=0,
        sku=None,
        status=status,
        category=category.name if category is not None else "",
        category_id=category.id if category is not None else None,
    )
    db.add(product)
    db.flush()
    if created_at is not None:
        product.created_at = created_at
        db.flush()
    return product


def _make_mapped_slide(
    db: Session,
    store: Store,
    category: Category,
    *,
    position: int,
    featured_product_id: uuid.UUID | None = None,
    admin_is_enabled: bool = True,
    is_active: bool = True,
    title: str | None = None,
) -> StorefrontSlide:
    slide = StorefrontSlide(
        store_id=store.id,
        title=title or category.name,
        subtitle=None,
        image_url="https://example.com/hero.jpg",
        cta_url=None,
        cta_label=None,
        position=position,
        target_category_id=category.id,
        is_active=is_active,
        category_id=category.id,
        featured_product_id=featured_product_id,
        admin_is_enabled=admin_is_enabled,
    )
    db.add(slide)
    db.flush()
    return slide


def _snapshot_state(db: Session, store_id: uuid.UUID) -> dict:
    slides = list(
        db.execute(
            select(StorefrontSlide)
            .where(StorefrontSlide.store_id == store_id)
            .order_by(StorefrontSlide.id.asc())
        ).scalars().all()
    )
    return {
        "count": len(slides),
        "rows": [
            (
                s.id,
                s.position,
                s.category_id,
                s.featured_product_id,
                s.admin_is_enabled,
                s.is_active,
                s.title,
                s.image_url,
            )
            for s in slides
        ],
    }


def test_eligible_category_with_valid_manual_featured_product(db_session: Session) -> None:
    store = _make_store(db_session, "a.example.com", "A")
    cat = _make_category(db_session, store, name="Shoes", slug="shoes", status="Active")
    p = _make_product(db_session, store, cat, name="Runner", slug="runner", status="Active", image="https://img/x.png")
    slide = _make_mapped_slide(db_session, store, cat, position=1, featured_product_id=p.id, admin_is_enabled=True)
    before = _snapshot_state(db_session, store.id)

    item = assemble_storefront_hero_mapping_read(db_session, slide)

    assert item.id == slide.id
    assert item.store_id == store.id
    assert item.category_id == cat.id
    assert item.position == 1
    assert item.admin_is_enabled is True
    assert item.is_active is True
    assert item.featured_product_id == p.id  # stored preserved
    assert item.manual_featured_product_valid is True
    assert item.featured_resolution_source == "manual"
    assert item.effective_featured_product is not None
    assert item.effective_featured_product.id == p.id
    assert item.effective_featured_product.name == "Runner"
    assert item.effective_featured_product.slug == "runner"
    assert item.effective_featured_product.status == "Active"
    assert item.eligibility.category_active is True
    assert item.eligibility.has_eligible_active_product is True
    assert item.eligibility.is_publicly_eligible is True
    assert _snapshot_state(db_session, store.id) == before  # read-only


def test_invalid_stored_manual_selection_preserved_while_fallback_returned(db_session: Session) -> None:
    store = _make_store(db_session, "a.example.com", "A")
    cat = _make_category(db_session, store, name="Shoes", slug="shoes", status="Active")
    invalid_manual = _make_product(
        db_session, store, cat, name="Draft Shoe", slug="draft-shoe", status="Draft", image=""
    )
    fallback = _make_product(
        db_session, store, cat, name="Active Shoe", slug="active-shoe", status="Active", image="https://img/f.png"
    )
    slide = _make_mapped_slide(db_session, store, cat, position=1, featured_product_id=invalid_manual.id)
    before = _snapshot_state(db_session, store.id)

    item = assemble_storefront_hero_mapping_read(db_session, slide)

    assert item.featured_product_id == invalid_manual.id  # stored invalid selection preserved
    assert item.manual_featured_product_valid is False
    assert item.featured_resolution_source == "fallback"
    assert item.effective_featured_product is not None
    assert item.effective_featured_product.id == fallback.id
    assert item.eligibility.is_publicly_eligible is True
    assert _snapshot_state(db_session, store.id) == before


def test_fallback_prefers_products_with_images(db_session: Session) -> None:
    store = _make_store(db_session, "a.example.com", "A")
    cat = _make_category(db_session, store, name="Shoes", slug="shoes", status="Active")
    now = datetime.now(timezone.utc)
    newer_no_image = _make_product(
        db_session,
        store,
        cat,
        name="New No Image",
        slug="new-no-image",
        status="Active",
        image="",
        created_at=now,
    )
    older_with_image = _make_product(
        db_session,
        store,
        cat,
        name="Old With Image",
        slug="old-with-image",
        status="Active",
        image="https://img/old.png",
        created_at=now - timedelta(days=1),
    )
    slide = _make_mapped_slide(db_session, store, cat, position=1, featured_product_id=None)

    item = assemble_storefront_hero_mapping_read(db_session, slide)

    assert newer_no_image.id != older_with_image.id
    assert item.manual_featured_product_valid is False
    assert item.featured_resolution_source == "fallback"
    assert item.effective_featured_product is not None
    assert item.effective_featured_product.id == older_with_image.id


def test_no_eligible_product_returns_none(db_session: Session) -> None:
    store = _make_store(db_session, "a.example.com", "A")
    cat = _make_category(db_session, store, name="Empty", slug="empty", status="Active")
    # no active products
    slide = _make_mapped_slide(db_session, store, cat, position=1)

    item = assemble_storefront_hero_mapping_read(db_session, slide)

    assert item.featured_resolution_source == "none"
    assert item.effective_featured_product is None
    assert item.manual_featured_product_valid is False
    assert item.eligibility.category_active is True
    assert item.eligibility.has_eligible_active_product is False
    assert item.eligibility.is_publicly_eligible is False


def test_disabled_and_ineligible_mappings_remain_present(db_session: Session) -> None:
    store = _make_store(db_session, "a.example.com", "A")
    active_cat = _make_category(db_session, store, name="Active", slug="active", status="Active")
    _make_product(db_session, store, active_cat, name="P", slug="p", status="Active", image="https://img/p.png")
    draft_cat = _make_category(db_session, store, name="Draft", slug="draft", status="Draft")  # ineligible category
    _make_product(db_session, store, draft_cat, name="D", slug="d", status="Active", image="https://img/d.png")

    enabled_slide = _make_mapped_slide(db_session, store, active_cat, position=1, admin_is_enabled=True)
    disabled_ineligible_slide = _make_mapped_slide(
        db_session, store, draft_cat, position=2, admin_is_enabled=False
    )

    resp = list_storefront_hero_mappings(db_session, store.id, page=1, page_size=20)

    assert resp.total == 2
    assert [i.category_id for i in resp.items] == [active_cat.id, draft_cat.id]
    by_cat = {i.category_id: i for i in resp.items}
    assert by_cat[active_cat.id].admin_is_enabled is True
    assert by_cat[active_cat.id].eligibility.is_publicly_eligible is True
    assert by_cat[draft_cat.id].id == disabled_ineligible_slide.id
    assert by_cat[draft_cat.id].admin_is_enabled is False  # disabled remains present
    assert by_cat[draft_cat.id].eligibility.category_active is False
    assert by_cat[draft_cat.id].eligibility.is_publicly_eligible is False  # ineligible remains present


def test_pagination_totals_boundaries_and_deterministic_ordering(db_session: Session) -> None:
    store = _make_store(db_session, "a.example.com", "A")
    cats = []
    for i in range(5):
        c = _make_category(db_session, store, name=f"Cat {i}", slug=f"cat-{i}", status="Active")
        _make_product(db_session, store, c, name=f"P{i}", slug=f"p-{i}", status="Active", image="")
        cats.append(c)
    # create in non-position order to verify deterministic ordering by position asc, id asc
    slides = [
        _make_mapped_slide(db_session, store, cats[2], position=3),
        _make_mapped_slide(db_session, store, cats[0], position=1),
        _make_mapped_slide(db_session, store, cats[4], position=5),
        _make_mapped_slide(db_session, store, cats[1], position=2),
        _make_mapped_slide(db_session, store, cats[3], position=4),
    ]

    page1 = list_storefront_hero_mappings(db_session, store.id, page=1, page_size=2)
    page2 = list_storefront_hero_mappings(db_session, store.id, page=2, page_size=2)
    page3 = list_storefront_hero_mappings(db_session, store.id, page=3, page_size=2)
    out_of_range = list_storefront_hero_mappings(db_session, store.id, page=99, page_size=2)

    assert page1.total == 5 and page1.page == 1 and page1.page_size == 2
    assert [i.position for i in page1.items] == [1, 2]
    assert page2.total == 5 and [i.position for i in page2.items] == [3, 4]
    assert page3.total == 5 and [i.position for i in page3.items] == [5]
    assert out_of_range.total == 5 and out_of_range.items == [] and out_of_range.page == 99

    all_items = page1.items + page2.items + page3.items
    assert [i.category_id for i in all_items] == [cats[0].id, cats[1].id, cats[2].id, cats[3].id, cats[4].id]
    # deterministic/stable: position asc, id asc
    keys = [(i.position, i.id) for i in all_items]
    assert keys == sorted(keys)


def test_store_isolation_records_from_other_store_never_appear(db_session: Session) -> None:
    store_a = _make_store(db_session, "a.example.com", "A")
    store_b = _make_store(db_session, "b.example.com", "B")

    cat_a = _make_category(db_session, store_a, name="A Cat", slug="a-cat", status="Active")
    _make_product(db_session, store_a, cat_a, name="A Prod", slug="a-prod", status="Active", image="")
    slide_a = _make_mapped_slide(db_session, store_a, cat_a, position=1)

    cat_b = _make_category(db_session, store_b, name="B Cat", slug="b-cat", status="Active")
    _make_product(db_session, store_b, cat_b, name="B Prod", slug="b-prod", status="Active", image="")
    slide_b = _make_mapped_slide(db_session, store_b, cat_b, position=1)

    before_b = _snapshot_state(db_session, store_b.id)

    resp_a = list_storefront_hero_mappings(db_session, store_a.id, page=1, page_size=20)

    assert resp_a.total == 1
    assert len(resp_a.items) == 1
    assert resp_a.items[0].id == slide_a.id
    assert resp_a.items[0].store_id == store_a.id
    assert resp_a.items[0].category_id == cat_a.id
    assert all(i.store_id == store_a.id for i in resp_a.items)
    assert slide_b.id not in {i.id for i in resp_a.items}
    # read-only and no cross-store side effects
    assert _snapshot_state(db_session, store_b.id) == before_b
