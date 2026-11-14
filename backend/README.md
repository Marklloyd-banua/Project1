# FastAPI Backend Foundation (Phase 7B)

Standalone FastAPI backend foundation for `saas-admin-template`.

**Phase 1 scope (implemented):** app structure, versioned API router (`/api/v1`), health/readiness endpoints, environment-based config, configurable CORS, centralized exception handling, basic tests, **plus SQLAlchemy 2.x engine/session wiring, an Alembic scaffold (empty migration chain), and a real database connectivity probe in `/health/ready` (safe generic errors; details only in server logs).**

**Not implemented yet (by design):** authentication/JWT/RBAC (Phase 3), storefront/business APIs, or frontend integration changes.

## Requirements

- Python 3.11+ recommended (tested target: Python 3.13 in development environment; compatibility may vary).
- Use a **project-local virtual environment** (do not install globally).

## Setup (local / Linux / CI)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # optional; defaults work for local dev
```

## Run the server

```bash
cd backend
source .venv/bin/activate  # if using venv
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API base: `http://127.0.0.1:8000/api/v1`
- Health: `GET /api/v1/health`
- Readiness (HTTP/config + real database connectivity probe; safe generic errors): `GET /api/v1/health/ready`
- OpenAPI docs: `GET /api/v1/docs`

## Database (Phase 1)

- `DATABASE_URL` selects the engine (default `sqlite:///./dev.db`; **no tables are created in Phase 1**).
- Local Termux PostgreSQL testing uses the pure-Python `pg8000` driver (`postgresql+pg8000://…`); production/CI may use `psycopg` on Linux via the same URL pattern. Driver choice is made entirely by the URL.
- `/health/ready` failures return a generic `checks.database: "error"` — technical details (exceptions, connection strings) never appear in HTTP responses, only in server logs.

## Database (Phase 2)

- **Models:** `app/models/` (SQLAlchemy 2.x, 19 tables registered on `Base.metadata`). The hand-written Alembic migrations are the **authoritative PostgreSQL DDL**; model metadata is the portable (SQLite + PostgreSQL) equivalent used by tests.
- **Migrations:** run from `backend/` with `DATABASE_URL` set:
  ```bash
  alembic upgrade head     # creates all 19 Phase 2 tables (revisions 0001..0004)
  alembic downgrade base   # drops them in reverse dependency order
  alembic history          # shows the 0001..0004 chain
  ```
  Revision chain: `0001` staff/stores/memberships/order-counters → `0002` categories/products/images/inventory-adjustments → `0003` storefront slides/sections/settings/footer links → `0004` customers/addresses/carts/orders/history.
- **PostgreSQL 15+ REQUIRED.** Migrations use PG-15+ column-list referential actions (`ON DELETE SET NULL (category_id)` etc.), PG regex CHECKs (`~`), triggers, and `JSONB`. On PostgreSQL < 15 the migrations fail with a syntax error.
- **No extensions required:** UUIDs use core `gen_random_uuid()`; lowercase invariants use `CHECK (col = lower(col))` (no `citext`); JSONB is core `pg_catalog`.
- **Privileges (`backend/db/privileges.sql`):** an ops script run **at deploy time** (NOT a migration) as the migration/owner role or a superuser. It creates the least-privilege LOGIN role `app_runtime` (set its password out-of-band; nothing is committed here) and grants full CRUD on the 17 ordinary tables, but **SELECT/INSERT only** on the append-only ledgers `inventory_adjustments` and `order_status_history` (`UPDATE`/`DELETE` explicitly revoked → SQLSTATE `42501`). The application runtime `DATABASE_URL` must use ONLY `app_runtime`; the migration/owner role is for schema surgery (e.g. Alembic), never runtime traffic.
- **Isolation model:** every child table carries `store_id` and every cross-table FK is composite `(store_id, referenced_id)` → `UNIQUE(store_id, id)` targets, making cross-store references physically impossible. Ledger rows are `ON DELETE RESTRICT` (history preserved; store deletion is gated by it).

## Configuration (environment variables)

See `backend/.env.example` for placeholders (no real credentials). Key variables:

- `APP_NAME`, `APP_ENV`, `DEBUG`
- `API_V1_PREFIX` (default `/api/v1`)
- `CORS_ORIGINS` (comma-separated)
- `CORS_ALLOW_CREDENTIALS`

## Tests

```bash
cd backend
source .venv/bin/activate  # if using venv
PYTHONPATH=. pytest -q
```

Phase 2 test split:

- `tests/test_models.py` — portable; runs on both CI jobs (SQLite metadata checks, FK-target uniqueness, ORM defaults, dashboard-vocabulary assertions).
- `tests/test_migrations.py`, `tests/test_constraints_pg.py`, `tests/test_order_numbering_pg.py`, `tests/test_ledger_immutability_pg.py` — **PostgreSQL-only** (marked skip on SQLite). They run against an **isolated, disposable** database (`phase2_ci_<random>`) created from the CI `DATABASE_URL` server, migrated with `alembic upgrade head`, and dropped afterwards — the main `DATABASE_URL` database is never touched, so the Phase 1 "no tables" contract still holds.
- The ledger tests create a disposable `ci_runtime_phase2` role and assert `UPDATE`/`DELETE` on the ledgers fail with SQLSTATE `42501` while `INSERT` and owner-role updates succeed.

## Android Termux notes / limitations

- **Do not install Python packages globally.** Use a local venv inside `backend/`.
- `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `httpx`, and `pytest` are pure-Python or commonly available, but **installation on Android/Termux may fail** depending on:
  - `pydantic-core`/Rust-built wheels availability for the device/Python version (pydantic v2 dependency behavior can vary).
  - Optional native speedups (e.g., `uvloop`, `httptools` are not required by this foundation; `uvicorn[standard]` is avoided here to reduce native build risk).
  - SSL/cert/toolchain/package-index issues in Termux.
- If installs fail, capture the exact error and run backend setup/tests in a compatible Linux environment (CI, remote dev container, or remote host) while keeping frontend dev in Termux.
- **Report actual test/install results honestly;** do not claim success unless commands were executed successfully.

## Frontend safety

This phase adds only the `backend/` directory and does **not** modify existing React frontend files, root `package.json`, mock behavior, or frontend mock/API selection.
