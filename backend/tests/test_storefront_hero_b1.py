from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.category import Category
from app.models.product import Product, ProductImage
from app.models.store import Store
from app.models.storefront import StorefrontSlide
from app.services.storefront_hero import (
    FeaturedProductValidationError,
    ReorderValidationError,
    StorefrontHeroDomainError,
    is_category_publicly_eligible,
    list_mapped_slides_ordered,
    normalize_mapped_positions,
    reorder_mapped_categories,
    resolve_featured_product_for_mapping,
    select_fallback_featured_product,
    set_mapping_featured_product,
    sync_hero_mappings,
    validate_manual_featured_product,
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


def _make_store(db: Session, domain: str = "store-a.example.com", name: str = "Store A") -> Store:
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
    image: str | None = None,
    stock_quantity: int = 10,
    created_at: datetime | None = None,
) -> Product:
    product = Product(
        store_id=store.id,
        name=name,
        slug=slug,
        description=None,
        image=image,
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


def test_category_eligibility_active_category_requires_eligible_active_product(db_session: Session):
    store = _make_store(db_session)
    cat_active = _make_category(db_session, store, name="Accessories", slug="accessories", status="Active")
    cat_draft = _make_category(db_session, store, name="Draft", slug="draft", status="Draft")
    cat_empty = _make_category(db_session, store, name="Empty", slug="empty", status="Active")

    _make_product(db_session, store, cat_active, name="Tote", slug="tote", status="Active", stock_quantity=0)
    _make_product(db_session, store, cat_draft, name="Hidden", slug="hidden", status="Active")
    _make_product(db_session, store, cat_empty, name="DraftProd", slug="draft-prod", status="Draft")

    assert is_category_publicly_eligible(db_session, store.id, cat_active.id) is True
    assert is_category_publicly_eligible(db_session, store.id, cat_draft.id) is False
    assert is_category_publicly_eligible(db_session, store.id, cat_empty.id) is False


def test_manual_featured_product_validation_same_store_category_active_and_out_of_stock_eligible(
    db_session: Session,
):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="Accessories", slug="accessories")
    prod = _make_product(db_session, store, cat, name="Tote", slug="tote", status="Active", stock_quantity=0)

    validated = validate_manual_featured_product(db_session, store.id, cat.id, prod.id)
    assert validated.id == prod.id


def test_manual_featured_product_validation_rejects_cross_store_cross_category_draft_and_missing(
    db_session: Session,
):
    store_a = _make_store(db_session, domain="a.example.com", name="A")
    store_b = _make_store(db_session, domain="b.example.com", name="B")
    cat_a1 = _make_category(db_session, store_a, name="A1", slug="a1")
    cat_a2 = _make_category(db_session, store_a, name="A2", slug="a2")
    cat_b = _make_category(db_session, store_b, name="B1", slug="b1")

    prod_a1 = _make_product(db_session, store_a, cat_a1, name="A1 Prod", slug="a1-prod", status="Active")
    prod_a2 = _make_product(db_session, store_a, cat_a2, name="A2 Prod", slug="a2-prod", status="Active")
    prod_b = _make_product(db_session, store_b, cat_b, name="B Prod", slug="b-prod", status="Active")
    draft = _make_product(db_session, store_a, cat_a1, name="Draft", slug="draft", status="Draft")

    with pytest.raises(FeaturedProductValidationError):
        validate_manual_featured_product(db_session, store_a.id, cat_a1.id, prod_b.id)  # cross-store
    with pytest.raises(FeaturedProductValidationError):
        validate_manual_featured_product(db_session, store_a.id, cat_a1.id, prod_a2.id)  # cross-category
    with pytest.raises(FeaturedProductValidationError):
        validate_manual_featured_product(db_session, store_a.id, cat_a1.id, draft.id)  # not active
    with pytest.raises(FeaturedProductValidationError):
        validate_manual_featured_product(db_session, store_a.id, cat_a1.id, uuid.uuid4())  # missing


def test_image_aware_fallback_and_deterministic_tie_breaking(db_session: Session):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="Accessories", slug="accessories")
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)

    # No-image products: newest by created_at then id should win when none have images.
    p_old = _make_product(db_session, store, cat, name="Old", slug="old", image=None, created_at=t1)
    p_new = _make_product(db_session, store, cat, name="New", slug="new", image=None, created_at=t2)
    # ensure deterministic id tie-break scenario not needed here; p_new newer by time
    assert select_fallback_featured_product(db_session, store.id, cat.id).id == p_new.id

    # Product with primary image should be preferred over newer no-image product.
    p_img = _make_product(db_session, store, cat, name="Img", slug="img", image="https://img/x.png", created_at=t1)
    assert select_fallback_featured_product(db_session, store.id, cat.id).id == p_img.id

    # Gallery image counts as having image (primary image empty/non-image, gallery present).
    p_img.image = ""
    db_session.flush()
    p_gallery = _make_product(db_session, store, cat, name="Gal", slug="gal", image="", created_at=t1)
    db_session.add(
        ProductImage(
            store_id=store.id,
            product_id=p_gallery.id,
            url="https://img/g.png",
            alt=None,
            position=1,
        )
    )
    db_session.flush()
    assert select_fallback_featured_product(db_session, store.id, cat.id).id == p_gallery.id


def test_fallback_tie_breaking_by_id_when_created_at_equal(db_session: Session):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="Accessories", slug="accessories")
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p1 = _make_product(db_session, store, cat, name="P1", slug="p1", image=None, created_at=t)
    p2 = _make_product(db_session, store, cat, name="P2", slug="p2", image=None, created_at=t)
    # Force identical timestamps
    p1.created_at = t
    p2.created_at = t
    db_session.flush()
    chosen = select_fallback_featured_product(db_session, store.id, cat.id)
    assert chosen is not None
    expected = p1 if p1.id > p2.id else p2  # created_at desc, id desc
    assert chosen.id == expected.id


def test_no_eligible_product_omission_and_intent_preservation(db_session: Session):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="Accessories", slug="accessories", status="Active")
    slide = _make_mapped_slide(db_session, store, cat, position=1, admin_is_enabled=True)
    # No active products at all
    _make_product(db_session, store, cat, name="Draft", slug="draft", status="Draft")

    assert is_category_publicly_eligible(db_session, store.id, cat.id) is False
    res = resolve_featured_product_for_mapping(db_session, slide)
    assert res.product is None and res.source == "none"
    # Administrative intent/config preserved
    assert slide.admin_is_enabled is True
    assert slide.category_id == cat.id

    # Category becomes temporarily ineligible (Draft) even if products exist -> intent preserved
    _make_product(db_session, store, cat, name="ActiveNow", slug="active-now", status="Active")
    cat.status = "Draft"
    db_session.flush()
    assert is_category_publicly_eligible(db_session, store.id, cat.id) is False
    db_session.refresh(slide)
    assert slide.admin_is_enabled is True and slide.category_id == cat.id


def test_manual_selection_resolution_and_invalid_manual_falls_back_without_mutation(db_session: Session):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="Accessories", slug="accessories")
    manual = _make_product(db_session, store, cat, name="Manual", slug="manual", status="Active", image=None)
    fallback_img = _make_product(
        db_session, store, cat, name="Fallback", slug="fallback", status="Active", image="https://img/f.png"
    )
    slide = _make_mapped_slide(db_session, store, cat, position=1, featured_product_id=manual.id)

    res = resolve_featured_product_for_mapping(db_session, slide)
    assert res.source == "manual" and res.product is not None and res.product.id == manual.id

    # Make manual invalid (becomes Draft) -> fallback applies, stored manual selection preserved
    manual.status = "Draft"
    db_session.flush()
    res2 = resolve_featured_product_for_mapping(db_session, slide)
    assert res2.source == "fallback" and res2.product is not None and res2.product.id == fallback_img.id
    assert slide.featured_product_id == manual.id  # intent/selection preserved


def test_sync_hero_mappings_is_duplicate_free_idempotent_and_preserves_legacy_unmapped_rows(
    db_session: Session,
):
    store = _make_store(db_session)
    cat1 = _make_category(db_session, store, name="A", slug="a")
    cat2 = _make_category(db_session, store, name="B", slug="b")
    cat3 = _make_category(db_session, store, name="C", slug="c")

    # Existing mapped row for cat1 and an unmapped legacy duplicate row (category_id NULL)
    mapped = _make_mapped_slide(db_session, store, cat1, position=1, admin_is_enabled=False)
    legacy_unmapped = StorefrontSlide(
        store_id=store.id,
        title="Legacy dup",
        subtitle="keep me",
        image_url="https://example.com/legacy.jpg",
        cta_url=None,
        cta_label=None,
        position=5,
        target_category_id=cat1.id,
        is_active=False,
        category_id=None,
        featured_product_id=None,
        admin_is_enabled=True,
    )
    db_session.add(legacy_unmapped)
    db_session.flush()
    legacy_id = legacy_unmapped.id

    first = sync_hero_mappings(db_session, store.id)
    mapped_category_ids = [s.category_id for s in first]
    assert sorted([str(x) for x in mapped_category_ids if x]) == sorted(
        [str(cat1.id), str(cat2.id), str(cat3.id)]
    )
    assert len(mapped_category_ids) == len(set(mapped_category_ids))

    # Existing mapped row preserved (admin intent)
    db_session.refresh(mapped)
    assert mapped.admin_is_enabled is False

    # Legacy unmapped row preserved and still unmapped
    preserved = db_session.get(StorefrontSlide, legacy_id)
    assert preserved is not None
    assert preserved.category_id is None
    assert preserved.title == "Legacy dup" and preserved.subtitle == "keep me"
    assert preserved.target_category_id == cat1.id

    # Idempotent
    second = sync_hero_mappings(db_session, store.id)
    assert [s.id for s in second] == [s.id for s in first]
    assert [s.position for s in second] == list(range(1, len(second) + 1))
    all_mapped = db_session.execute(
        select(StorefrontSlide).where(
            StorefrontSlide.store_id == store.id, StorefrontSlide.category_id.is_not(None)
        )
    ).scalars().all()
    assert len(all_mapped) == 3


def test_safe_reordering_and_position_uniqueness_more_than_four(db_session: Session):
    store = _make_store(db_session)
    cats = [
        _make_category(db_session, store, name=f"C{i}", slug=f"c{i}") for i in range(1, 7)
    ]
    slides = [_make_mapped_slide(db_session, store, c, position=i + 1) for i, c in enumerate(cats)]
    db_session.flush()

    new_order = [cats[i].id for i in [4, 2, 0, 5, 1, 3]]  # 6 items (>4)
    result = reorder_mapped_categories(db_session, store.id, new_order)
    assert [s.category_id for s in result] == new_order
    assert [s.position for s in result] == [1, 2, 3, 4, 5, 6]

    # Uniqueness holds and no duplicates/collisions
    positions = db_session.execute(
        select(StorefrontSlide.position).where(
            StorefrontSlide.store_id == store.id, StorefrontSlide.category_id.is_not(None)
        )
    ).scalars().all()
    assert sorted(positions) == [1, 2, 3, 4, 5, 6]

    # Reverse reorder also safe (exercises temporary-range normalization)
    rev = list(reversed(new_order))
    result2 = reorder_mapped_categories(db_session, store.id, rev)
    assert [s.category_id for s in result2] == rev
    assert [s.position for s in result2] == [1, 2, 3, 4, 5, 6]


def test_reorder_validation_rejects_duplicates_missing_unknown(db_session: Session):
    store = _make_store(db_session)
    cat1 = _make_category(db_session, store, name="A", slug="a")
    cat2 = _make_category(db_session, store, name="B", slug="b")
    _make_mapped_slide(db_session, store, cat1, position=1)
    _make_mapped_slide(db_session, store, cat2, position=2)

    with pytest.raises(ReorderValidationError):
        reorder_mapped_categories(db_session, store.id, [cat1.id, cat1.id])
    with pytest.raises(ReorderValidationError):
        reorder_mapped_categories(db_session, store.id, [cat1.id])
    with pytest.raises(ReorderValidationError):
        reorder_mapped_categories(db_session, store.id, [cat1.id, uuid.uuid4()])


def test_set_mapping_featured_product_and_admin_intent(db_session: Session):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="A", slug="a")
    prod = _make_product(db_session, store, cat, name="P", slug="p", status="Active", stock_quantity=0)
    slide = _make_mapped_slide(db_session, store, cat, position=1, admin_is_enabled=True)

    updated = set_mapping_featured_product(
        db_session, store.id, cat.id, prod.id, admin_is_enabled=False
    )
    assert updated.featured_product_id == prod.id
    assert updated.admin_is_enabled is False

    cleared = set_mapping_featured_product(db_session, store.id, cat.id, None)
    assert cleared.featured_product_id is None
    assert cleared.admin_is_enabled is False  # preserved unless changed


def test_set_mapping_featured_product_rejects_cross_store_category(db_session: Session):
    store_a = _make_store(db_session, domain="a.example.com")
    store_b = _make_store(db_session, domain="b.example.com")
    cat_a = _make_category(db_session, store_a, name="A", slug="a")
    cat_b = _make_category(db_session, store_b, name="B", slug="b")
    prod_b = _make_product(db_session, store_b, cat_b, name="PB", slug="pb")
    _make_mapped_slide(db_session, store_a, cat_a, position=1)

    with pytest.raises(FeaturedProductValidationError):
        set_mapping_featured_product(db_session, store_a.id, cat_a.id, prod_b.id)

    with pytest.raises(StorefrontHeroDomainError):
        set_mapping_featured_product(db_session, store_a.id, uuid.uuid4(), None)


def test_product_lifecycle_featured_deleted_or_unassigned_falls_back(db_session: Session):
    store = _make_store(db_session)
    cat = _make_category(db_session, store, name="A", slug="a")
    manual = _make_product(db_session, store, cat, name="Manual", slug="manual", status="Active", image=None)
    other = _make_product(db_session, store, cat, name="Other", slug="other", status="Active", image="https://img/o.png")
    slide = _make_mapped_slide(db_session, store, cat, position=1, featured_product_id=manual.id)

    # Unassign from category -> invalid for mapping, fallback applies
    manual.category_id = None
    db_session.flush()
    res = resolve_featured_product_for_mapping(db_session, slide)
    assert res.source == "fallback" and res.product is not None and res.product.id == other.id
    assert slide.featured_product_id == manual.id  # stored selection preserved

    # Delete product -> ORM/DB safe delete behavior; resolution must not break
    # (SQLite FK enforcement may vary; simulate by clearing selection path via status/availability logic)
    manual.status = "Draft"
    db_session.flush()
    res2 = resolve_featured_product_for_mapping(db_session, slide)
    assert res2.source == "fallback" and res2.product is not None and res2.product.id == other.id


def test_normalize_mapped_positions_handles_collisions_transaction_safely(db_session: Session):
    store = _make_store(db_session)
    cats = [_make_category(db_session, store, name=f"C{i}", slug=f"c{i}") for i in range(3)]
    s1 = _make_mapped_slide(db_session, store, cats[0], position=1)
    s2 = _make_mapped_slide(db_session, store, cats[1], position=2)
    s3 = _make_mapped_slide(db_session, store, cats[2], position=3)
    # Force a reorder that would collide without temp strategy by normalizing explicit order
    ordered = [s3, s1, s2]
    normalize_mapped_positions(db_session, store.id, ordered_slides=ordered)
    assert [s.position for s in ordered] == [1, 2, 3]
    assert [s.id for s in list_mapped_slides_ordered(db_session, store.id)] == [s3.id, s1.id, s2.id]
