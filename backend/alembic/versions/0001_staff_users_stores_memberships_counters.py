"""Migration 0001 — staff_users, stores, store_memberships, store_order_counters.

Hand-written PostgreSQL DDL mirroring backend/app/models/{staff_user,store}.py
(source of truth). PostgreSQL-only features carried here per the approved
design: hostname-format regex CHECK and the counter-initializing trigger.
Downgrade drops everything this migration creates, in reverse dependency order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("global_role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_staff_users"),
        sa.UniqueConstraint("email", name="uq_staff_users_email"),
        sa.CheckConstraint("email = lower(email)", name="ck_staff_users_email_lowercase"),
        sa.CheckConstraint("length(password_hash) <= 255", name="ck_staff_users_password_hash_length"),
        sa.CheckConstraint(
            "global_role IN ('administrator','manager','viewer')",
            name="ck_staff_users_global_role_vocabulary",
        ),
    )

    op.create_table(
        "stores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=False, server_default="Free"),
        sa.Column("mrr", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("logo_image_url", sa.String(length=2048), nullable=True),
        sa.Column("banner_image_url", sa.String(length=2048), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("phone_number", sa.String(length=50), nullable=True),
        sa.Column("business_address", sa.String(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("date_format", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_stores"),
        sa.UniqueConstraint("domain", name="uq_stores_domain"),
        sa.CheckConstraint("domain = lower(domain)", name="ck_stores_domain_lowercase"),
        # Dashboard hostname-only pattern (resourceForm.ts:35), POSIX-safe form.
        sa.CheckConstraint(
            "domain ~ '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$'",
            name="ck_stores_domain_format",
        ),
        sa.CheckConstraint(
            "plan IN ('Free','Starter','Professional','Enterprise')",
            name="ck_stores_plan_vocabulary",
        ),
        sa.CheckConstraint("mrr >= 0", name="ck_stores_mrr_nonnegative"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_stores_currency_iso_alpha3",
        ),
    )

    op.create_table(
        "store_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="store_memberships_store_fk"
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"], ["staff_users.id"], ondelete="CASCADE",
            name="store_memberships_staff_user_fk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_store_memberships"),
        sa.UniqueConstraint("store_id", "staff_user_id", name="membership_unique"),
        sa.CheckConstraint(
            "role IN ('owner','manager','viewer')", name="ck_store_memberships_role_vocabulary"
        ),
    )
    # One owner per store (partial unique index).
    op.create_index(
        "uq_one_owner_per_store",
        "store_memberships",
        ["store_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index(
        "ix_store_memberships_staff_user_id", "store_memberships", ["staff_user_id"]
    )

    op.create_table(
        "store_order_counters",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_order_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE", name="store_order_counters_store_fk"
        ),
        sa.PrimaryKeyConstraint("store_id", name="pk_store_order_counters"),
        sa.CheckConstraint(
            "last_order_number >= 0", name="ck_store_order_counters_last_order_number_nonnegative"
        ),
    )

    # Every store starts with counter 0; first allocated order number is 1.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_stores_init_counter() RETURNS trigger AS $$
        BEGIN
            INSERT INTO store_order_counters (store_id, last_order_number)
            VALUES (NEW.id, 0)
            ON CONFLICT (store_id) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_stores_init_counter
        AFTER INSERT ON stores
        FOR EACH ROW EXECUTE FUNCTION fn_stores_init_counter();
        """
    )


def downgrade() -> None:
    # Reverse dependency order: trigger/function first, then tables.
    op.execute("DROP TRIGGER IF EXISTS trg_stores_init_counter ON stores;")
    op.execute("DROP FUNCTION IF EXISTS fn_stores_init_counter();")
    op.drop_table("store_order_counters")
    op.drop_index("ix_store_memberships_staff_user_id", table_name="store_memberships")
    op.drop_index("uq_one_owner_per_store", table_name="store_memberships")
    op.drop_table("store_memberships")
    op.drop_table("stores")
    op.drop_table("staff_users")
