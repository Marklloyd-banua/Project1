from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.models.category import Category
from app.models.product import Product
from app.models.store import Store
from app.models.storefront import StorefrontSlide


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
ALLOWED_PORTS = frozenset({5432})
_DISPOSABLE_DB_NAME_RE = re.compile(r"^b1_hero_[0-9a-f]{12}$")


def _guard_disposable_db_name(dbname: str) -> None:
    if not _DISPOSABLE_DB_NAME_RE.fullmatch(dbname):
        raise AssertionError(f"Refusing to operate on non-disposable database name: {dbname!r}")


def _validated_b16_url():
    raw = os.environ.get("B16_TEST_DATABASE_URL")
    if raw is None or not raw.strip():
        pytest.skip("B1 PostgreSQL schema tests require B16_TEST_DATABASE_URL")
    if os.environ.get("NORTHSTAR_ALLOW_DISPOSABLE_PG_TEST_DB") != "1":
        pytest.skip(
            "B1 PostgreSQL schema tests require explicit opt-in "
            "NORTHSTAR_ALLOW_DISPOSABLE_PG_TEST_DB=1"
        )
    url = make_url(raw)
    driver = (url.drivername or "").lower()
    if not (driver == "postgresql" or driver.startswith("postgresql+")):
        pytest.skip("B16_TEST_DATABASE_URL must be a PostgreSQL URL")
    host = (url.host or "").strip().lower()
    port = url.port if url.port is not None else 5432
    if host not in ALLOWED_HOSTS or port not in ALLOWED_PORTS or not url.database:
        pytest.skip("B16_TEST_DATABASE_URL is not in the allowed disposable test-server configuration")
    return url


def _create_and_migrate_temp_db(to_revision: str) -> tuple[str, str]:
    """Create disposable DB, migrate to target revision, return (server_admin_url, db_url)."""
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings

    base = _validated_b16_url()
    dbname = f"b1_hero_{uuid.uuid4().hex[:12]}"
    _guard_disposable_db_name(dbname)
    admin_url = base.set(database="postgres").render_as_string(hide_password=False)
    db_url = base.set(database=dbname).render_as_string(hide_password=False)

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        admin.dispose()

    previous_env = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = db_url
        get_settings.cache_clear()
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, to_revision)
    finally:
        if previous_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_env
        get_settings.cache_clear()
    return admin_url, db_url


def _drop_temp_db(admin_url: str, dbname: str) -> None:
    _guard_disposable_db_name(dbname)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _db_name_from_url(db_url: str) -> str:
    return make_url(db_url).database or ""


@pytest.fixture()
def temp_pg_db_to_0003():
    admin_url, db_url = _create_and_migrate_temp_db("0003")
    dbname = _db_name_from_url(db_url)
    try:
        yield db_url
    finally:
        try:
            _drop_temp_db(admin_url, dbname)
        except Exception as exc:  # noqa: BLE001
            print(f"CLEANUP ERROR dropping {dbname}: {exc!r}", file=sys.stderr)
            raise


def test_alembic_head_is_0005_and_storefront_slide_columns(pg_api_engine):
    """Migration 0005 applied: head revision and expected new columns/constraints exist."""
    with pg_api_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0005"

    insp = inspect(pg_api_engine)
    cols = {c["name"]: c for c in insp.get_columns("storefront_slides")}
    for name in ("category_id", "featured_product_id", "admin_is_enabled"):
        assert name in cols, f"missing column {name}"
    assert cols["category_id"]["nullable"] is True
    assert cols["featured_product_id"]["nullable"] is True
    assert cols["admin_is_enabled"]["nullable"] is False

    # Position min constraint present; legacy max-4 range constraint removed.
    # Verify real PostgreSQL constraint semantics via catalog metadata (authoritative for
    # actual name/definition), with reflection as a secondary view.
    with pg_api_engine.connect() as conn:
        pg_checks = conn.execute(
            text(
                """
                SELECT con.conname AS name, pg_get_constraintdef(con.oid) AS definition
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                WHERE rel.relname = 'storefront_slides'
                  AND nsp.nspname = current_schema()
                  AND con.contype = 'c'
                """
            )
        ).mappings().all()

    def _norm_check_def(definition: str) -> str:
        # Normalize PostgreSQL check-definition formatting for semantic comparison.
        s = (definition or "").strip()
        if s.upper().startswith("CHECK"):
            s = s[5:].strip()
        # strip balanced outer parentheses layers added by pg_get_constraintdef/PG formatting
        while s.startswith("(") and s.endswith(")"):
            inner = s[1:-1].strip()
            if not inner:
                break
            s = inner
        return " ".join(s.replace('"', "").split()).lower()

    normalized_defs = [_norm_check_def(r["definition"]) for r in pg_checks]
    pg_check_names = {r["name"] for r in pg_checks}

    # Must enforce position >= 1 (actual DB semantics) and must not retain legacy 1..4 cap.
    assert any(d == "position >= 1" for d in normalized_defs), normalized_defs
    assert not any("between 1 and 4" in d or "between 1 and 4" in (r["definition"] or "").lower() for d, r in zip(normalized_defs, pg_checks)), [
        (r["name"], r["definition"]) for r in pg_checks
    ]
    assert "ck_storefront_slides_position_range" not in pg_check_names

    checks = {c["name"]: c for c in insp.get_check_constraints("storefront_slides")}
    assert "ck_storefront_slides_position_range" not in checks
    assert not any(
        "BETWEEN 1 AND 4" in (c.get("sqltext") or "").upper() for c in checks.values()
    )

    uniques = {u["name"]: u for u in insp.get_unique_constraints("storefront_slides")}
    assert "storefront_slides_position_unique" in uniques
    assert set(uniques["storefront_slides_position_unique"]["column_names"]) == {"store_id", "position"}
    # mapped category uniqueness (portable unique constraint)
    cat_unique = uniques.get("uq_storefront_slides_store_category_mapping")
    assert cat_unique is not None
    assert set(cat_unique["column_names"]) == {"store_id", "category_id"}

    fks = insp.get_foreign_keys("storefront_slides")
    fk_names = {fk.get("name") for fk in fks}
    assert "storefront_slides_store_category_fk" in fk_names  # legacy target FK preserved
    assert "storefront_slides_store_category_mapping_fk" in fk_names
    assert "storefront_slides_store_featured_product_fk" in fk_names


def test_more_than_four_mapped_slides_and_position_uniqueness(pg_api_session_factory):
    with pg_api_session_factory() as db:
        store = Store(name="S", owner="O", domain="b1-many.example.com")
        db.add(store)
        db.flush()
        for i in range(1, 7):
            cat = Category(store_id=store.id, name=f"C{i}", slug=f"c{i}", status="Active")
            db.add(cat)
            db.flush()
            db.add(
                StorefrontSlide(
                    store_id=store.id,
                    title=f"C{i}",
                    image_url="https://example.com/h.jpg",
                    position=i,
                    target_category_id=cat.id,
                    is_active=True,
                    category_id=cat.id,
                    featured_product_id=None,
                    admin_is_enabled=True,
                )
            )
        db.commit()

    with pg_api_session_factory() as db:
        count = db.execute(
            text("SELECT count(*) FROM storefront_slides WHERE store_id = :sid"),
            {"sid": store.id},
        ).scalar_one()
        assert count == 6
        max_pos = db.execute(
            text("SELECT max(position) FROM storefront_slides WHERE store_id = :sid"),
            {"sid": store.id},
        ).scalar_one()
        assert max_pos == 6

        # Unique (store_id, position) preserved
        with pytest.raises(Exception):
            db.add(
                StorefrontSlide(
                    store_id=store.id,
                    title="dup",
                    image_url="https://example.com/h.jpg",
                    position=6,
                    is_active=True,
                )
            )
            db.commit()
        db.rollback()


def test_mapped_category_uniqueness_allows_unmapped_legacy_rows(pg_api_session_factory):
    with pg_api_session_factory() as db:
        store = Store(name="S", owner="O", domain="b1-uniq.example.com")
        db.add(store)
        db.flush()
        cat = Category(store_id=store.id, name="A", slug="a", status="Active")
        db.add(cat)
        db.flush()

        # Two unmapped legacy rows (category_id NULL) allowed
        db.add_all(
            [
                StorefrontSlide(
                    store_id=store.id,
                    title="L1",
                    image_url="https://example.com/1.jpg",
                    position=1,
                    target_category_id=None,
                    is_active=True,
                    category_id=None,
                ),
                StorefrontSlide(
                    store_id=store.id,
                    title="L2",
                    image_url="https://example.com/2.jpg",
                    position=2,
                    target_category_id=None,
                    is_active=True,
                    category_id=None,
                ),
            ]
        )
        db.commit()

        # One mapped row for category is fine
        mapped = StorefrontSlide(
            store_id=store.id,
            title="M",
            image_url="https://example.com/m.jpg",
            position=3,
            target_category_id=cat.id,
            is_active=True,
            category_id=cat.id,
        )
        db.add(mapped)
        db.commit()

        # Second mapped row for same (store, category) rejected
        with pytest.raises(Exception):
            db.add(
                StorefrontSlide(
                    store_id=store.id,
                    title="M2",
                    image_url="https://example.com/m2.jpg",
                    position=4,
                    target_category_id=cat.id,
                    is_active=True,
                    category_id=cat.id,
                )
            )
            db.commit()
        db.rollback()


def test_featured_product_fk_safe_delete_sets_null_only(pg_api_session_factory):
    with pg_api_session_factory() as db:
        store = Store(name="S", owner="O", domain="b1-fk.example.com")
        db.add(store)
        db.flush()
        cat = Category(store_id=store.id, name="A", slug="a", status="Active")
        db.add(cat)
        db.flush()
        prod = Product(
            store_id=store.id,
            name="P",
            slug="p",
            image=None,
            price=10.00,
            stock_quantity=1,
            low_stock_threshold=0,
            status="Active",
            category=cat.name,
            category_id=cat.id,
        )
        db.add(prod)
        db.flush()
        slide = StorefrontSlide(
            store_id=store.id,
            title="A",
            image_url="https://example.com/a.jpg",
            position=1,
            target_category_id=cat.id,
            is_active=True,
            category_id=cat.id,
            featured_product_id=prod.id,
            admin_is_enabled=True,
        )
        db.add(slide)
        db.commit()
        slide_id = slide.id
        prod_id = prod.id

    with pg_api_session_factory() as db:
        # Delete product -> featured_product_id must be nulled, mapping row preserved
        db.execute(text("DELETE FROM products WHERE id = :pid"), {"pid": prod_id})
        db.commit()

    with pg_api_session_factory() as db:
        row = db.execute(
            text(
                "SELECT store_id, title, subtitle, image_url, cta_url, cta_label, position, "
                "target_category_id, is_active, category_id, featured_product_id, admin_is_enabled "
                "FROM storefront_slides WHERE id = :sid"
            ),
            {"sid": slide_id},
        ).mappings().one()
        # Column-list SET NULL behavior (actual DB): only featured_product_id is cleared.
        assert str(row["store_id"]) == str(store.id)
        assert row["title"] == "A"
        assert row["subtitle"] is None
        assert row["image_url"] == "https://example.com/a.jpg"
        assert row["cta_url"] is None
        assert row["cta_label"] is None
        assert row["position"] == 1
        assert str(row["target_category_id"]) == str(cat.id)
        assert row["is_active"] is True
        assert str(row["category_id"]) == str(cat.id)
        assert row["featured_product_id"] is None
        assert row["admin_is_enabled"] is True


def test_legacy_backfill_unambiguous_duplicate_and_unmappable_rows_preserved(temp_pg_db_to_0003):
    """Upgrade 0003->head backfills category_id deterministically and preserves legacy rows."""
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings

    db_url = temp_pg_db_to_0003
    engine = create_engine(db_url, future=True)
    try:
        with engine.begin() as conn:
            store_id = conn.execute(
                text("INSERT INTO stores (name, owner, domain) VALUES ('S','O','b1-backfill.example.com') RETURNING id")
            ).scalar_one()
            cat1 = conn.execute(
                text("INSERT INTO categories (store_id, name, slug, status) VALUES (:s,'A','a','Active') RETURNING id"),
                {"s": store_id},
            ).scalar_one()
            cat2 = conn.execute(
                text("INSERT INTO categories (store_id, name, slug, status) VALUES (:s,'B','b','Active') RETURNING id"),
                {"s": store_id},
            ).scalar_one()

            # Unambiguous legacy row (cat1 only once) -> should map
            unambig_id = conn.execute(
                text(
                    "INSERT INTO storefront_slides (store_id,title,subtitle,image_url,cta_url,cta_label,position,target_category_id,is_active) "
                    "VALUES (:s,'U','sub','https://ex/u.jpg',NULL,NULL,1,:c,true) RETURNING id"
                ),
                {"s": store_id, "c": cat1},
            ).scalar_one()

            # Duplicate legacy rows targeting same category (cat2) -> preserve all; canonical (lowest position,id) mapped
            dup_a = conn.execute(
                text(
                    "INSERT INTO storefront_slides (store_id,title,subtitle,image_url,cta_url,cta_label,position,target_category_id,is_active) "
                    "VALUES (:s,'D1','dsub1','https://ex/d1.jpg',NULL,NULL,2,:c,true) RETURNING id"
                ),
                {"s": store_id, "c": cat2},
            ).scalar_one()
            dup_b = conn.execute(
                text(
                    "INSERT INTO storefront_slides (store_id,title,subtitle,image_url,cta_url,cta_label,position,target_category_id,is_active) "
                    "VALUES (:s,'D2','dsub2','https://ex/d2.jpg',NULL,NULL,3,:c,false) RETURNING id"
                ),
                {"s": store_id, "c": cat2},
            ).scalar_one()

            # Unmappable legacy row (no target_category_id) -> category_id remains NULL
            unmapped_id = conn.execute(
                text(
                    "INSERT INTO storefront_slides (store_id,title,subtitle,image_url,cta_url,cta_label,position,target_category_id,is_active) "
                    "VALUES (:s,'N','nsub','https://ex/n.jpg',NULL,NULL,4,NULL,true) RETURNING id"
                ),
                {"s": store_id},
            ).scalar_one()
    finally:
        engine.dispose()

    previous_env = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = db_url
        get_settings.cache_clear()
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
    finally:
        if previous_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_env
        get_settings.cache_clear()

    engine = create_engine(db_url, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, title, subtitle, image_url, position, target_category_id, category_id, is_active "
                    "FROM storefront_slides WHERE store_id = :s ORDER BY position ASC, id ASC"
                ),
                {"s": store_id},
            ).mappings().all()
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        assert version == "0005"
        assert len(rows) == 4  # none deleted/discarded
        by_id = {str(r["id"]): r for r in rows}

        u = by_id[str(unambig_id)]
        assert str(u["category_id"]) == str(cat1)
        assert str(u["target_category_id"]) == str(cat1)
        assert u["title"] == "U"

        da = by_id[str(dup_a)]
        dbrow = by_id[str(dup_b)]
        # canonical = lowest position then id; dup_a has position 2 < 3
        assert str(da["category_id"]) == str(cat2)
        assert dbrow["category_id"] is None  # preserved but unmapped
        # legacy fields/content preserved
        assert str(da["target_category_id"]) == str(cat2)
        assert str(dbrow["target_category_id"]) == str(cat2)
        assert da["title"] == "D1" and da["subtitle"] == "dsub1"
        assert dbrow["title"] == "D2" and dbrow["subtitle"] == "dsub2" and dbrow["is_active"] is False

        n = by_id[str(unmapped_id)]
        assert n["category_id"] is None
        assert n["target_category_id"] is None
        assert n["title"] == "N" and n["subtitle"] == "nsub"
    finally:
        engine.dispose()
