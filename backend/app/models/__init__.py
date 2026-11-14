"""SQLAlchemy models (Phase 2).

Importing this package registers every ORM table on ``Base.metadata`` (19
tables across four approved migrations). The hand-written Alembic migrations
under ``alembic/versions/`` are the AUTHORITATIVE PostgreSQL DDL; this
metadata carries the portable (SQLite + PostgreSQL) equivalent for local and
SQLite-job testing.
"""

from __future__ import annotations

from app.models.base import Base
from app.models.staff_user import StaffUser
from app.models.store import Store, StoreMembership, StoreOrderCounter
from app.models.category import Category
from app.models.product import Product, ProductImage
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.storefront import (
    StorefrontFooterLink,
    StorefrontSection,
    StorefrontSettings,
    StorefrontSlide,
)
from app.models.customer import Customer, CustomerAddress
from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem, OrderStatusHistory

__all__ = [
    "Base",
    "StaffUser",
    "Store",
    "StoreMembership",
    "StoreOrderCounter",
    "Category",
    "Product",
    "ProductImage",
    "InventoryAdjustment",
    "StorefrontSlide",
    "StorefrontSection",
    "StorefrontSettings",
    "StorefrontFooterLink",
    "Customer",
    "CustomerAddress",
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    "OrderStatusHistory",
]

EXPECTED_TABLE_NAMES = sorted(
    [
        "staff_users",
        "stores",
        "store_memberships",
        "store_order_counters",
        "categories",
        "products",
        "product_images",
        "inventory_adjustments",
        "storefront_slides",
        "storefront_sections",
        "storefront_settings",
        "storefront_footer_links",
        "customers",
        "customer_addresses",
        "carts",
        "cart_items",
        "orders",
        "order_items",
        "order_status_history",
    ]
)
