from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import hash_password
from app.models.staff_user import StaffUser
from app.schemas.auth import normalize_email

BOOTSTRAP_LOCK_KEY = 913_337_031_300_001


def _require_bootstrap_database_url() -> str:
    raw_url = os.environ.get("BOOTSTRAP_DATABASE_URL")
    if not raw_url or not raw_url.strip():
        raise RuntimeError(
            "BOOTSTRAP_DATABASE_URL must be explicitly configured and must not fall back to DATABASE_URL."
        )
    url = raw_url.strip()
    try:
        parsed = make_url(url)
    except Exception as exc:  # noqa: BLE001 - convert malformed URL into clear CLI/runtime error.
        raise RuntimeError(
            "BOOTSTRAP_DATABASE_URL must be a valid PostgreSQL URL using driver 'postgresql' or 'postgresql+pg8000'."
        ) from exc
    if parsed.drivername not in {"postgresql", "postgresql+pg8000"}:
        raise RuntimeError(
            "BOOTSTRAP_DATABASE_URL must use PostgreSQL driver 'postgresql' or 'postgresql+pg8000'; "
            f"got '{parsed.drivername}'."
        )
    return url


def _prompt_password_twice() -> str:
    password = getpass.getpass("Administrator password: ")
    confirm = getpass.getpass("Confirm administrator password: ")
    if password != confirm:
        raise RuntimeError("Passwords do not match.")
    return password


def _build_session_factory(database_url: str):
    engine = create_engine(database_url, future=True)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def bootstrap_administrator(email: str, full_name: str, password: str, database_url: str) -> str:
    normalized_email = normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required.")
    if not full_name or not full_name.strip():
        raise ValueError("A non-empty full name is required.")

    try:
        parsed = make_url(database_url)
    except Exception as exc:  # noqa: BLE001 - convert malformed URL into clear runtime error.
        raise RuntimeError(
            "BOOTSTRAP_DATABASE_URL must be a valid PostgreSQL URL using driver 'postgresql' or 'postgresql+pg8000'."
        ) from exc
    if parsed.drivername not in {"postgresql", "postgresql+pg8000"}:
        raise RuntimeError(
            "BOOTSTRAP_DATABASE_URL must use PostgreSQL driver 'postgresql' or 'postgresql+pg8000'; "
            f"got '{parsed.drivername}'."
        )

    password_hash = hash_password(password)
    engine, SessionLocal = _build_session_factory(database_url)
    try:
        with SessionLocal() as session:
            with session.begin():
                # PostgreSQL transaction-level advisory lock to serialize bootstrap attempts.
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BOOTSTRAP_LOCK_KEY})

                existing_admin = session.execute(
                    select(StaffUser.id).where(StaffUser.global_role == "administrator")
                ).scalar_one_or_none()
                if existing_admin is not None:
                    raise RuntimeError("Administrator bootstrap refused: an administrator account already exists.")

                existing_email = session.execute(
                    select(StaffUser.id).where(StaffUser.email == normalized_email)
                ).scalar_one_or_none()
                if existing_email is not None:
                    raise RuntimeError("Administrator bootstrap refused: an account with this email already exists.")

                user = StaffUser(
                    email=normalized_email,
                    full_name=full_name.strip(),
                    password_hash=password_hash,
                    global_role="administrator",
                    status="Active",
                )
                session.add(user)
                session.flush()
                return str(user.id)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-time Northstar administrator bootstrap.")
    parser.add_argument("--email", help="Administrator email address (prompted if omitted)")
    parser.add_argument("--full-name", dest="full_name", help="Administrator full name (prompted if omitted)")
    args = parser.parse_args(argv)

    try:
        database_url = _require_bootstrap_database_url()
        email = (args.email or input("Administrator email: ")).strip()
        full_name = (args.full_name or input("Administrator full name: ")).strip()
        password = _prompt_password_twice()
        user_id = bootstrap_administrator(
            email=email,
            full_name=full_name,
            password=password,
            database_url=database_url,
        )
        print(f"Administrator created: {user_id}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should report a clear failure without traceback noise by default.
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
