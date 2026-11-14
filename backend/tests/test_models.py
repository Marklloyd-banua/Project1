"""Phase 2 model tests (portable; runs on both CI jobs).

Validates the SQLAlchemy metadata itself — independent of any database:
table registry, foreign-key target uniqueness (the composite same-store
targets), ORM default behavior on SQLite, and the structural invariants
(no ORM relationships that could mutate ledgers/stock, fulfillment never
touches stock at the model layer).
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import EXPECTED_TABLE_NAMES, Base
from app.models import (  # noqa: F401 — import registers every table
    Cart, CartItem, Category, Customer, CustomerAddress, InventoryAdjustment,
    Order, OrderItem, OrderStatusHistory, Product, ProductImage, StaffUser,
    Store, StoreMembership, StoreOrderCounter, StorefrontFooterLink,
    StorefrontSection, StorefrontSettings, StorefrontSlide,
)
from decimal import Decimal


def test_metadata_registers_exactly_19_tables():
    assert sorted(Base.metadata.tables.keys()) == EXPECTED_TABLE_NAMES


def test_every_fk_target_is_unique_in_metadata():
    """Every FK (single or composite) must point at a PK or UNIQUE constraint —
    this is what makes the composite (store_id, id) same-store targets valid."""
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if type(constraint).__name__ != "ForeignKeyConstraint":
                continue
            target = constraint.referred_table
            target_sets: set[tuple[str, ...]] = set()
            for c in target.constraints:
                if c.name and type(c).__name__ == "UniqueConstraint":
                    target_sets.add(tuple(sorted(col.name for col in c.columns)))
                elif c.name and type(c).__name__ == "PrimaryKeyConstraint":
                    target_sets.add(tuple(sorted(col.name for col in c.columns)))
            referred_cols = tuple(sorted(el.column.name for el in constraint.elements))
            assert referred_cols in target_sets, (
                f"{table.name}.{constraint.name} -> "
                f"{target.name}{referred_cols} is not a unique target"
            )


def test_models_declare_no_orm_relationships():
    """FK-only model graph: no relationship cascades can mutate ledgers or
    stock behind the API's back."""
    for mapper in Base.registry.mappers:
        assert not mapper.relationships, (
            f"{mapper.class_.__name__} unexpectedly declares ORM relationships"
        )


def test_fulfillment_never_touches_stock_at_model_level():
    """Nothing in the order models writes products.stock_quantity."""
    assert "stock_quantity" not in Base.metadata.tables["orders"].columns
    assert "stock_quantity" not in Base.metadata.tables["order_items"].columns
    assert "stock_quantity" not in Base.metadata.tables["order_status_history"].columns


def test_orm_defaults_uuid_and_timestamps():
    """On SQLite (metadata dialect) the ORM must fill id/created_at/updated_at."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            store = Store(name="S", owner="O", domain="orm-defaults.example.com")
            session.add(store)
            session.flush()
            assert isinstance(store.id, uuid.UUID)
            assert store.created_at is not None
            assert store.updated_at is not None
            assert store.currency == "USD"
            assert session.execute(
                select(StoreOrderCounter.last_order_number).where(
                    StoreOrderCounter.store_id == store.id
                )
            ).scalar_one_or_none() is None  # trigger is migration-only (PG)
            counter = StoreOrderCounter(store_id=store.id)
            session.add(counter)
            session.flush()
            assert counter.last_order_number == 0
    finally:
        engine.dispose()


def test_product_money_columns_use_numeric_12_2():
    from sqlalchemy import Numeric

    for table, col in [
        ("products", "price"),
        ("orders", "total"),
        ("order_items", "line_total"),
        ("cart_items", "unit_price"),
        ("stores", "mrr"),
    ]:
        assert isinstance(Base.metadata.tables[table].columns[col].type, Numeric)
        assert Base.metadata.tables[table].columns[col].type.precision == 12
        assert Base.metadata.tables[table].columns[col].type.scale == 2


def test_order_status_vocabularies_match_dashboard_unions():
    """The exact strings from src/types/models.ts must be the only DB values."""
    order = Base.metadata.tables["orders"]
    checks = {
        c.name: c.sqltext.text for c in order.constraints if type(c).__name__ == "CheckConstraint"
    }
    payment = checks["ck_orders_payment_status_vocabulary"]
    for status in ("Unpaid", "Pending", "Paid", "Failed", "Refunded", "Partially paid"):
        assert f"'{status}'" in payment
    fulfillment = checks["ck_orders_fulfillment_status_vocabulary"]
    for status in (
        "Unfulfilled", "Processing", "Partially fulfilled", "Shipped",
        "Delivered", "Cancelled", "Returned",
    ):
        assert f"'{status}'" in fulfillment


def test_decimal_money_round_trip_on_sqlite():
    """Sanity: Numeric(12,2) returns Decimal through the ORM on SQLite."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            store = Store(name="S", owner="O", domain="money.example.com")
            session.add(store)
            session.flush()
            product = Product(
                store_id=store.id, name="Tee", slug="tee",
                price=Decimal("10.50"), stock_quantity=3,
            )
            session.add(product)
            session.flush()
            session.refresh(product)
            assert product.price == Decimal("10.50")
    finally:
        engine.dispose()
