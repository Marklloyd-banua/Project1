-- backend/db/privileges.sql — Phase 2 append-only ledger protection (ops script).
--
-- NOT an Alembic migration: fresh CI databases migrate cleanly without any
-- roles existing. Run this AT DEPLOY TIME against the live database, as the
-- migration/owner role (the role Alembic connects as) or a superuser.
--
-- Design (approved):
--   * The migration/owner role OWNS all Phase 2 tables (it created them via
--     Alembic) and keeps full privileges — used only for approved schema
--     surgery, never by application runtime traffic.
--   * app_runtime is a separate, least-privilege LOGIN role; the application's
--     runtime DATABASE_URL must use ONLY this role.
--   * inventory_adjustments and order_status_history are append-only ledgers:
--     the runtime role receives SELECT, INSERT only. UPDATE and DELETE are
--     explicitly revoked (belt and braces — default is nothing anyway).
--   * No table ownership is transferred here; no RLS is introduced.

BEGIN;

-- Create the runtime role if it does not exist (no password is set here;
-- provision it out-of-band, e.g.:
--   ALTER ROLE app_runtime PASSWORD '...' ;
-- or use a managed secret. Never commit real credentials.)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
        CREATE ROLE app_runtime LOGIN;
    END IF;
END
$$;

-- Schema access (search_path safety: the app must set search_path explicitly
-- or connect with the role's default; we grant USAGE on public).
GRANT USAGE ON SCHEMA public TO app_runtime;

-- Ordinary tables: full CRUD for the runtime application (Phase 2 models;
-- Phase 3 endpoints will use these).
GRANT SELECT, INSERT, UPDATE, DELETE ON
    staff_users,
    stores,
    store_memberships,
    store_order_counters,
    categories,
    products,
    product_images,
    storefront_slides,
    storefront_sections,
    storefront_settings,
    storefront_footer_links,
    customers,
    customer_addresses,
    carts,
    cart_items,
    orders,
    order_items
TO app_runtime;

-- Append-only ledgers: SELECT and INSERT only.
GRANT SELECT, INSERT ON
    inventory_adjustments,
    order_status_history
TO app_runtime;

-- Explicit revocation on the ledgers (belt and braces; also covers any
-- accidental prior grant).
REVOKE UPDATE, DELETE ON
    inventory_adjustments,
    order_status_history
FROM app_runtime;

COMMIT;
