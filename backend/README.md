# FastAPI Backend Foundation (Phase 7B)

Standalone FastAPI backend foundation for `saas-admin-template`.

**Phase 1 scope (implemented):** app structure, versioned API router (`/api/v1`), health/readiness endpoints, environment-based config, configurable CORS, centralized exception handling, basic tests, **plus SQLAlchemy 2.x engine/session wiring, an Alembic scaffold (empty migration chain), and a real database connectivity probe in `/health/ready` (safe generic errors; details only in server logs).**

**Not implemented yet (by design):** database models/tables/migrations (Phase 2), authentication/JWT/RBAC (Phase 3), storefront/business APIs, or frontend integration changes.

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
- Alembic is scaffolded (`alembic.ini`, `alembic/env.py`) with an **empty migration chain**; `alembic upgrade head` is a no-op until Phase 2 migrations are added.
- `/health/ready` failures return a generic `checks.database: "error"` — technical details (exceptions, connection strings) never appear in HTTP responses, only in server logs.

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
