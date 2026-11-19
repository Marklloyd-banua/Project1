"""B1: Category-driven storefront hero domain/service logic.

Implements deterministic eligibility, manual featured-product validation,
image-aware fallback, safe owner-controlled ordering, duplicate-free mapping
synchronization, and preservation of administrative intent for temporarily
ineligible mappings.

No public/admin API or UI behavior is implemented here (B1 foundation only).
Service functions that mutate mappings/positions are transactional within the
provided SQLAlchemy Session (callers control commit/rollback boundaries).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.product import Product, ProductImage
from app.models.storefront import StorefrontSlide


# ---------------------------------------------------------------------------
# Domain results / helpers
# ---------------------------------------------------------------------------


class StorefrontHeroDomainError(ValueError):
    """Base class for storefront hero domain validation errors."""


class FeaturedProductValidationError(StorefrontHeroDomainError):
    """Manual featured product is invalid for the target store/category mapping."""


class ReorderValidationError(StorefrontHeroDomainError):
    """Owner-controlled reorder request is invalid."""


@dataclass(frozen=True)
class FeaturedResolution:
    """Resolved featured product for a category mapping."""

    product: Product | None
    source: str  # "manual" | "fallback" | "none"


def _normalize_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _product_has_image(db: Session, product: Product) -> bool:
    """Image-aware rule: primary image URL present or any gallery image row exists."""
    if product.image and str(product.image).strip():
        return True
    # Use relationship if loaded; otherwise check existence deterministically.
    images = getattr(product, "images", None)
    if images is not None:
        try:
            if len(images) > 0:
                return True
        except TypeError:
            pass
    exists = db.execute(
        select(ProductImage.id).where(ProductImage.product_id == product.id).limit(1)
    ).scalar_one_or_none()
    return exists is not None


def _eligible_active_products_stmt(store_id: uuid.UUID, category_id: uuid.UUID):
    return (
        select(Product)
        .where(
            Product.store_id == store_id,
            Product.category_id == category_id,
            Product.status == "Active",
        )
        .order_by(Product.created_at.desc(), Product.id.desc())
    )


def list_eligible_active_products(
    db: Session, store_id: uuid.UUID | str, category_id: uuid.UUID | str
) -> list[Product]:
    """Active same-store/category products (including out-of-stock), deterministic order."""
    sid = _normalize_uuid(store_id)
    cid = _normalize_uuid(category_id)
    return list(db.execute(_eligible_active_products_stmt(sid, cid)).scalars().all())


def category_is_active(db: Session, store_id: uuid.UUID, category_id: uuid.UUID) -> bool:
    status = db.execute(
        select(Category.status).where(
            Category.store_id == store_id, Category.id == category_id
        )
    ).scalar_one_or_none()
    return status == "Active"


def category_has_eligible_active_product(
    db: Session, store_id: uuid.UUID, category_id: uuid.UUID
) -> bool:
    exists = db.execute(
        select(Product.id)
        .where(
            Product.store_id == store_id,
            Product.category_id == category_id,
            Product.status == "Active",
        )
        .limit(1)
    ).scalar_one_or_none()
    return exists is not None


def is_category_publicly_eligible(
    db: Session, store_id: uuid.UUID | str, category_id: uuid.UUID | str
) -> bool:
    """Active category with at least one eligible active product in same store/category."""
    sid = _normalize_uuid(store_id)
    cid = _normalize_uuid(category_id)
    return category_is_active(db, sid, cid) and category_has_eligible_active_product(
        db, sid, cid
    )


def _is_product_eligible_for_category(
    product: Product, store_id: uuid.UUID, category_id: uuid.UUID
) -> bool:
    return (
        product.store_id == store_id
        and product.category_id == category_id
        and product.status == "Active"
    )


def validate_manual_featured_product(
    db: Session,
    store_id: uuid.UUID | str,
    category_id: uuid.UUID | str,
    product_id: uuid.UUID | str,
) -> Product:
    """Validate a manual featured product is active and belongs to same store/category.

    Out-of-stock active products are eligible. Raises FeaturedProductValidationError on
    cross-store/category mismatch, missing product, or ineligible status/assignment.
    """
    sid = _normalize_uuid(store_id)
    cid = _normalize_uuid(category_id)
    pid = _normalize_uuid(product_id)

    # Ensure category belongs to store (authoritative mapping context).
    category = db.execute(
        select(Category).where(Category.store_id == sid, Category.id == cid)
    ).scalar_one_or_none()
    if category is None:
        raise FeaturedProductValidationError("Category does not belong to store.")

    product = db.execute(
        select(Product).where(Product.id == pid)
    ).scalar_one_or_none()
    if product is None:
        raise FeaturedProductValidationError("Featured product not found.")

    # Cross-store or cross-category rejection (explicit, do not rely on FK alone).
    if product.store_id != sid or product.category_id != cid:
        raise FeaturedProductValidationError(
            "Featured product must belong to the same store and mapped category."
        )
    if product.status != "Active":
        raise FeaturedProductValidationError("Featured product must be active.")
    return product


def select_fallback_featured_product(
    db: Session, store_id: uuid.UUID | str, category_id: uuid.UUID | str
) -> Product | None:
    """Newest eligible active product with image, else newest eligible active product.

    Deterministic tie-breaking: created_at DESC, id DESC. Out-of-stock eligible.
    """
    sid = _normalize_uuid(store_id)
    cid = _normalize_uuid(category_id)
    candidates = list_eligible_active_products(db, sid, cid)
    if not candidates:
        return None
    # candidates already ordered by created_at DESC, id DESC
    for product in candidates:
        if _product_has_image(db, product):
            return product
    return candidates[0]


def resolve_featured_product_for_mapping(
    db: Session, slide: StorefrontSlide
) -> FeaturedResolution:
    """Resolve featured product for a mapped slide (manual if valid, else fallback).

    Preserves administrative intent: if manual selection is no longer valid/eligible,
    resolution falls back without mutating the stored selection here.
    """
    if slide.category_id is None:
        return FeaturedResolution(product=None, source="none")

    store_id = slide.store_id
    category_id = slide.category_id

    # Manual selection takes precedence when valid and eligible.
    if slide.featured_product_id is not None:
        try:
            manual = validate_manual_featured_product(
                db, store_id, category_id, slide.featured_product_id
            )
            # Category eligibility matters for public visibility, but manual product validity
            # is still authoritative for "manual if valid" resolution context.
            if _is_product_eligible_for_category(manual, store_id, category_id):
                return FeaturedResolution(product=manual, source="manual")
        except FeaturedProductValidationError:
            pass

    fallback = select_fallback_featured_product(db, store_id, category_id)
    if fallback is None:
        return FeaturedResolution(product=None, source="none")
    return FeaturedResolution(product=fallback, source="fallback")


# ---------------------------------------------------------------------------
# Mapping queries / mutation helpers (transactional)
# ---------------------------------------------------------------------------


def _mapped_slides_for_store_stmt(store_id: uuid.UUID):
    return select(StorefrontSlide).where(
        StorefrontSlide.store_id == store_id,
        StorefrontSlide.category_id.is_not(None),
    )


def list_mapped_slides_ordered(db: Session, store_id: uuid.UUID | str) -> list[StorefrontSlide]:
    sid = _normalize_uuid(store_id)
    stmt = _mapped_slides_for_store_stmt(sid).order_by(
        StorefrontSlide.position.asc(), StorefrontSlide.id.asc()
    )
    return list(db.execute(stmt).scalars().all())


def _next_safe_position_base(db: Session, store_id: uuid.UUID) -> int:
    max_pos = db.execute(
        select(func.coalesce(func.max(StorefrontSlide.position), 0)).where(
            StorefrontSlide.store_id == store_id
        )
    ).scalar_one()
    return int(max_pos) + 1


def normalize_mapped_positions(
    db: Session, store_id: uuid.UUID | str, *, ordered_slides: Sequence[StorefrontSlide] | None = None
) -> list[StorefrontSlide]:
    """Normalize mapped slide positions to contiguous 1..N in deterministic order.

    Transaction-safe strategy for UNIQUE(store_id, position): move affected mapped rows to a
    temporary range above the current store maximum, flush, then assign final contiguous
    positions. Does not disable constraints or use intermediate commits.
    """
    sid = _normalize_uuid(store_id)
    slides = (
        list(ordered_slides)
        if ordered_slides is not None
        else list_mapped_slides_ordered(db, sid)
    )
    if not slides:
        return []

    # Work on mapped rows in desired final order.
    base = _next_safe_position_base(db, sid)
    # Temporary phase: ensure no collisions with existing/final positions.
    for offset, slide in enumerate(slides, start=0):
        slide.position = base + offset
    db.flush()

    # Final contiguous positions in owner/deterministic order.
    for idx, slide in enumerate(slides, start=1):
        slide.position = idx
    db.flush()
    return slides


def sync_hero_mappings(db: Session, store_id: uuid.UUID | str) -> list[StorefrontSlide]:
    """Create missing mapped rows for store categories and normalize positions.

    - Duplicate-free by (store_id, category_id): preserves an existing mapped row if present;
      never creates a second mapped row for the same category.
    - Preserves all legacy/unmapped rows and their legacy fields.
    - Preserves administrative intent (admin_is_enabled/featured_product_id) on existing mappings.
    - Idempotent with respect to mapped coverage and contiguous ordering.
    - Newly created mappings are appended in deterministic category order (name ASC, id ASC)
      after existing mapped rows ordered by (position ASC, id ASC).
    """
    sid = _normalize_uuid(store_id)

    existing_mapped = list_mapped_slides_ordered(db, sid)
    mapped_category_ids = {s.category_id for s in existing_mapped if s.category_id is not None}

    # Consider all store categories for mapping coverage (admin intent/config preserved even if
    # temporarily ineligible); public eligibility is resolved at read/derivation time.
    categories = list(
        db.execute(
            select(Category)
            .where(Category.store_id == sid)
            .order_by(Category.name.asc(), Category.id.asc())
        ).scalars().all()
    )

    to_create: list[StorefrontSlide] = []
    # Assign safe temporary positions >= 1 before flush to satisfy position_min and avoid
    # collisions with existing rows; final contiguous positions are normalized below.
    temp_base = _next_safe_position_base(db, sid)
    for offset, category in enumerate(categories):
        if category.id in mapped_category_ids:
            continue
        slide = StorefrontSlide(
            store_id=sid,
            title=category.name,
            subtitle=None,
            image_url="https://placehold.co/1200x400?text=Hero",
            cta_url=None,
            cta_label=None,
            position=temp_base + offset,
            target_category_id=category.id,
            is_active=True,
            category_id=category.id,
            featured_product_id=None,
            admin_is_enabled=True,
        )
        db.add(slide)
        to_create.append(slide)
        mapped_category_ids.add(category.id)

    if to_create:
        db.flush()

    # Final deterministic order: existing mapped rows keep their relative order, new ones appended.
    refreshed_mapped = list_mapped_slides_ordered(db, sid)
    existing_ids = [s.id for s in existing_mapped]
    existing_set = set(existing_ids)
    ordered = [s for s in refreshed_mapped if s.id in existing_set]
    # Append any newly created rows (or any mapped rows not previously listed) in deterministic
    # category order (name ASC, id ASC) for idempotent, duplicate-free sync.
    appended = [s for s in refreshed_mapped if s.id not in existing_set]
    appended.sort(key=lambda s: ((s.title or "").lower(), s.id))
    final_order = ordered + appended

    normalize_mapped_positions(db, sid, ordered_slides=final_order)
    return final_order


def set_mapping_featured_product(
    db: Session,
    store_id: uuid.UUID | str,
    category_id: uuid.UUID | str,
    featured_product_id: uuid.UUID | str | None,
    *,
    admin_is_enabled: bool | None = None,
) -> StorefrontSlide:
    """Set or clear a mapping's manual featured product (and/or admin intent).

    Validates manual featured product belongs to same store and mapped category and is active.
    Preserves mapping row and admin intent; does not create duplicates.
    """
    sid = _normalize_uuid(store_id)
    cid = _normalize_uuid(category_id)

    slide = db.execute(
        select(StorefrontSlide).where(
            StorefrontSlide.store_id == sid,
            StorefrontSlide.category_id == cid,
        )
    ).scalar_one_or_none()
    if slide is None:
        raise StorefrontHeroDomainError("Category mapping not found for store.")

    if featured_product_id is None:
        slide.featured_product_id = None
    else:
        product = validate_manual_featured_product(db, sid, cid, featured_product_id)
        slide.featured_product_id = product.id

    if admin_is_enabled is not None:
        slide.admin_is_enabled = bool(admin_is_enabled)

    db.flush()
    return slide


def reorder_mapped_categories(
    db: Session,
    store_id: uuid.UUID | str,
    ordered_category_ids: Sequence[uuid.UUID | str],
) -> list[StorefrontSlide]:
    """Apply owner-controlled ordering for mapped categories, transaction-safely.

    The provided sequence must contain each currently mapped category_id exactly once
    (no duplicates, no missing, no unknown/cross-store ids). Positions are normalized to
    contiguous 1..N using the temporary-range strategy to avoid UNIQUE collisions.
    """
    sid = _normalize_uuid(store_id)
    try:
        normalized_ids = [_normalize_uuid(cid) for cid in ordered_category_ids]
    except Exception as exc:  # noqa: BLE001
        raise ReorderValidationError("Invalid category id in ordering.") from exc

    if len(set(normalized_ids)) != len(normalized_ids):
        raise ReorderValidationError("Duplicate category ids in ordering.")

    mapped = list_mapped_slides_ordered(db, sid)
    mapped_by_category = {s.category_id: s for s in mapped if s.category_id is not None}

    if set(normalized_ids) != set(mapped_by_category.keys()):
        raise ReorderValidationError(
            "Ordering must include each mapped category exactly once."
        )

    ordered_slides = [mapped_by_category[cid] for cid in normalized_ids]
    normalize_mapped_positions(db, sid, ordered_slides=ordered_slides)
    return ordered_slides
