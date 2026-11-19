"""Migration 0005 — category-driven storefront hero foundation.

Evolves storefront_slides (0003) for the approved Option R category-to-hero
mapping while preserving all legacy B1.5B/B1.6-compatible columns/rows/behavior.

Key changes:
- removes legacy max-4 position cap (keeps position >= 1 and UNIQUE(store_id, position))
- adds category_id (authoritative mapping, nullable for unmappable legacy rows)
- adds featured_product_id (nullable) and admin_is_enabled (preserves admin intent)
- adds composite FKs: (store_id,category_id)->categories ON DELETE CASCADE and
  (store_id,featured_product_id)->products ON DELETE SET NULL (featured_product_id only)
- enforces UNIQUE(store_id, category_id) for mapped rows (NULL category_id rows may repeat)
- deterministic, non-destructive backfill from target_category_id:
  * valid+unambiguous legacy targets -> category_id set
  * duplicate legacy targets for same (store,category) -> exactly one canonical row mapped
    (lowest position, then lowest id), remaining duplicates preserved but left unmapped
  * unmappable/NULL legacy targets -> category_id remains NULL

Downgrade limitations (documented): restoring the 1..4 cap fails if any store has
positions > 4 or more than 4 slides; dropping 0005 columns/FKs/constraints discards
category mapping, featured-product selection, and admin intent data. Downgrade is
intended only for controlled environments with compatible data; forward-fix preferred.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add category-driven mapping columns (additive, legacy-compatible defaults).
    op.add_column(
        "storefront_slides",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "storefront_slides",
        sa.Column("featured_product_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "storefront_slides",
        sa.Column(
            "admin_is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # 2) Remove legacy max-4 cap; retain minimum and unique (store_id, position).
    op.drop_constraint(
        "ck_storefront_slides_position_range", "storefront_slides", type_="check"
    )
    op.create_check_constraint(
        "ck_storefront_slides_position_min",
        "storefront_slides",
        "position >= 1",
    )

    # 3) Deterministic, non-destructive backfill.
    # Map rows where target_category_id is valid-in-context and unambiguous for the store.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                target_category_id,
                ROW_NUMBER() OVER (
                    PARTITION BY store_id, target_category_id
                    ORDER BY position ASC, id ASC
                ) AS rn,
                COUNT(*) OVER (
                    PARTITION BY store_id, target_category_id
                ) AS cnt
            FROM storefront_slides
            WHERE target_category_id IS NOT NULL
        )
        UPDATE storefront_slides AS s
        SET category_id = r.target_category_id
        FROM ranked AS r
        WHERE s.id = r.id
          AND r.cnt = 1;
        """
    )
    # Duplicate legacy targets: preserve all rows/legacy fields; map exactly one canonical row.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                target_category_id,
                ROW_NUMBER() OVER (
                    PARTITION BY store_id, target_category_id
                    ORDER BY position ASC, id ASC
                ) AS rn,
                COUNT(*) OVER (
                    PARTITION BY store_id, target_category_id
                ) AS cnt
            FROM storefront_slides
            WHERE target_category_id IS NOT NULL
        )
        UPDATE storefront_slides AS s
        SET category_id = r.target_category_id
        FROM ranked AS r
        WHERE s.id = r.id
          AND r.cnt > 1
          AND r.rn = 1;
        """
    )
    # target_category_id remains readable/unchanged for all rows (including unmapped duplicates).

    # 4) Add integrity constraints for new mapping/featured fields.
    op.create_foreign_key(
        "storefront_slides_store_category_mapping_fk",
        "storefront_slides",
        "categories",
        ["store_id", "category_id"],
        ["store_id", "id"],
        ondelete="CASCADE",
    )
    # Composite FK with PostgreSQL column-list SET NULL: deleting a product clears only
    # featured_product_id; store/category mapping and admin intent are preserved.
    op.execute(
        """
        ALTER TABLE storefront_slides
        ADD CONSTRAINT storefront_slides_store_featured_product_fk
        FOREIGN KEY (store_id, featured_product_id)
        REFERENCES products (store_id, id)
        ON DELETE SET NULL (featured_product_id);
        """
    )
    # Enforces uniqueness for mapped rows; NULL category_id (unmapped legacy rows) may repeat.
    op.create_unique_constraint(
        "uq_storefront_slides_store_category_mapping",
        "storefront_slides",
        ["store_id", "category_id"],
    )


def downgrade() -> None:
    # Reverse 0005. Check incompatibilities before destructive DDL and fail safely.
    # Restoring the legacy 1..4 cap is impossible if any slide position is outside 1..4.
    incompatible = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM storefront_slides WHERE position < 1 OR position > 4"
        )
    ).scalar_one()
    if int(incompatible) > 0:
        raise RuntimeError(
            "Cannot downgrade 0005: storefront_slides contains positions outside 1..4; "
            "legacy cap cannot be restored safely. Resolve incompatible positions/data "
            "before downgrade (mapping/intent data will be lost by this downgrade)."
        )

    op.drop_constraint(
        "uq_storefront_slides_store_category_mapping",
        "storefront_slides",
        type_="unique",
    )
    op.execute(
        "ALTER TABLE storefront_slides "
        "DROP CONSTRAINT IF EXISTS storefront_slides_store_featured_product_fk;"
    )
    op.drop_constraint(
        "storefront_slides_store_category_mapping_fk",
        "storefront_slides",
        type_="foreignkey",
    )

    op.drop_constraint(
        "ck_storefront_slides_position_min", "storefront_slides", type_="check"
    )
    op.create_check_constraint(
        "ck_storefront_slides_position_range",
        "storefront_slides",
        "position BETWEEN 1 AND 4",
    )

    op.drop_column("storefront_slides", "admin_is_enabled")
    op.drop_column("storefront_slides", "featured_product_id")
    op.drop_column("storefront_slides", "category_id")
