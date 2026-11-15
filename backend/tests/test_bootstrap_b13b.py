from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.cli import bootstrap_admin
from app.core.security import hash_password, verify_password
from app.models.base import Base
from app.models.staff_user import StaffUser
from tests.conftest import pg_database_url, requires_pg  # noqa: F401


def _session_factory_for_sqlite(tmp_path):
    db_path = tmp_path / "bootstrap.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def test_bootstrap_requires_explicit_bootstrap_database_url_env(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        bootstrap_admin._require_bootstrap_database_url()
    assert "BOOTSTRAP_DATABASE_URL" in str(excinfo.value)
    assert "DATABASE_URL" in str(excinfo.value)

    # Ensure no fallback to DATABASE_URL
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./should-not-be-used.db")
    monkeypatch.delenv("BOOTSTRAP_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        bootstrap_admin._require_bootstrap_database_url()


def test_bootstrap_uses_getpass_twice_and_not_cli_args_or_env(monkeypatch, tmp_path):
    # bootstrap_administrator is mocked in this SQLite test; it verifies prompting and
    # input handling, not PostgreSQL advisory locking.
    engine, _ = _session_factory_for_sqlite(tmp_path)
    engine.dispose()
    db_url = f"sqlite:///{tmp_path / 'bootstrap.db'}"

    calls = []

    def fake_getpass(prompt):
        calls.append(prompt)
        return "correct-horse-battery-staple"

    # Use an accepted PostgreSQL URL for explicit bootstrap env validation; the
    # monkeypatched bootstrap below performs no network/engine connection with it.
    monkeypatch.setenv("BOOTSTRAP_DATABASE_URL", "postgresql+pg8000://user:pass@localhost/bootstrap_test")
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", fake_getpass)
    # Even if env/args had password-like values, implementation must not read them.
    monkeypatch.setenv("ADMIN_PASSWORD", "env-secret-should-not-be-used")
    monkeypatch.setenv("PASSWORD", "env-secret-should-not-be-used")

    # Patch lock execution for SQLite (no pg advisory lock) and run core creation via function
    # by using a helper: we'll call main-like flow components directly to assert behavior.

    # Use a SQLite-compatible bootstrap by temporarily patching the lock statement execution.
    real_create_engine = bootstrap_admin.create_engine

    def create_sqlite_compatible_session_factory(database_url: str):
        eng = real_create_engine(database_url, future=True)
        SF = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, future=True)
        return eng, SF

    # Monkeypatch bootstrap_administrator to skip advisory lock on sqlite for this unit test of prompts/creation.
    def bootstrap_without_lock(email, full_name, password, database_url):
        from app.schemas.auth import normalize_email
        from app.core.security import hash_password
        normalized_email = normalize_email(email)
        if not normalized_email or "@" not in normalized_email:
            raise ValueError("A valid email address is required.")
        if not full_name or not full_name.strip():
            raise ValueError("A non-empty full name is required.")
        password_hash = hash_password(password)
        eng, SF = create_sqlite_compatible_session_factory(db_url)
        try:
            with SF() as session:
                with session.begin():
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
            eng.dispose()

    monkeypatch.setattr(bootstrap_admin, "bootstrap_administrator", bootstrap_without_lock)
    inputs = iter(["Admin@Example.com", "Alice Admin"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))

    rc = bootstrap_admin.main([])
    assert rc == 0
    assert len(calls) == 2
    assert "password" in calls[0].lower() and "confirm" in calls[1].lower()

    eng = create_engine(db_url, future=True)
    try:
        with eng.connect() as conn:
            row = conn.execute(text("select email, global_role, status, password_hash, full_name from staff_users")).mappings().one()
            assert row["email"] == "admin@example.com"  # normalized
            assert row["global_role"] == "administrator"
            assert row["status"] == "Active"
            assert row["full_name"] == "Alice Admin"
            assert row["password_hash"] is not None
            assert verify_password("correct-horse-battery-staple", row["password_hash"]) is True
    finally:
        eng.dispose()


def test_bootstrap_rejects_mismatched_passwords(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_DATABASE_URL", "postgresql+pg8000://user:pass@localhost/unused")
    answers = iter(["correct-horse-battery-staple", "different-password-123"])
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", lambda prompt: next(answers))
    with pytest.raises(RuntimeError) as excinfo:
        bootstrap_admin._prompt_password_twice()
    assert "do not match" in str(excinfo.value).lower()


def test_bootstrap_rejects_non_postgresql_database_url_before_engine_or_connection(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_DATABASE_URL", "sqlite:///./should-not-connect.db")

    def fail_create_engine(*args, **kwargs):
        raise AssertionError("create_engine must not be called for a rejected BOOTSTRAP_DATABASE_URL")

    monkeypatch.setattr(bootstrap_admin, "create_engine", fail_create_engine)
    monkeypatch.setattr(
        bootstrap_admin,
        "_build_session_factory",
        lambda database_url: (_ for _ in ()).throw(
            AssertionError("_build_session_factory must not be called for a rejected BOOTSTRAP_DATABASE_URL")
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        bootstrap_admin._require_bootstrap_database_url()
    assert "postgresql" in str(excinfo.value).lower()
    assert "sqlite" in str(excinfo.value).lower()


def test_bootstrap_administrator_rejects_non_postgresql_database_url_before_engine_or_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "should-not-be-created.db"

    def fail_create_engine(*args, **kwargs):
        raise AssertionError("create_engine must not be called for a rejected database_url")

    monkeypatch.setattr(bootstrap_admin, "create_engine", fail_create_engine)

    with pytest.raises(RuntimeError) as excinfo:
        bootstrap_admin.bootstrap_administrator(
            email="admin@example.com",
            full_name="Admin User",
            password="correct-horse-battery-staple",
            database_url=f"sqlite:///{db_path}",
        )

    assert "sqlite" in str(excinfo.value).lower()
    assert not db_path.exists()


def test_bootstrap_rejects_malformed_database_url(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_DATABASE_URL", "postgresql://user:pass@localhost:badport/db")

    def fail_create_engine(*args, **kwargs):
        raise AssertionError("create_engine must not be called for a malformed BOOTSTRAP_DATABASE_URL")

    monkeypatch.setattr(bootstrap_admin, "create_engine", fail_create_engine)

    with pytest.raises(RuntimeError) as excinfo:
        bootstrap_admin._require_bootstrap_database_url()
    assert "valid postgresql url" in str(excinfo.value).lower() or "postgresql" in str(excinfo.value).lower()


@requires_pg
def test_bootstrap_creates_admin_with_pg_advisory_lock_and_refuses_duplicates(pg_database_url):
    # Use the migrated disposable PG database from fixture.
    # First create should succeed; second must refuse without modifying existing account.
    user_id = bootstrap_admin.bootstrap_administrator(
        email="  BOOTSTRAP@Example.com  ",
        full_name="Bootstrap Admin",
        password="correct-horse-battery-staple",
        database_url=pg_database_url,
    )
    engine = create_engine(pg_database_url, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("select id, email, full_name, global_role, status, password_hash from staff_users")
            ).mappings().all()
            assert len(rows) == 1
            row = rows[0]
            assert str(row["id"]) == user_id
            assert row["email"] == "bootstrap@example.com"
            assert row["full_name"] == "Bootstrap Admin"
            assert row["global_role"] == "administrator"
            assert row["status"] == "Active"
            assert verify_password("correct-horse-battery-staple", row["password_hash"]) is True
            original = {
                "id": row["id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "global_role": row["global_role"],
                "status": row["status"],
                "password_hash": row["password_hash"],
            }

        with pytest.raises(RuntimeError) as excinfo:
            bootstrap_admin.bootstrap_administrator(
                email="another@example.com",
                full_name="Another",
                password="correct-horse-battery-staple",
                database_url=pg_database_url,
            )
        assert "already exists" in str(excinfo.value).lower()

        with engine.connect() as conn:
            rows_after = conn.execute(
                text("select id, email, full_name, global_role, status, password_hash from staff_users")
            ).mappings().all()
            assert len(rows_after) == 1
            row_after = rows_after[0]
            assert row_after["id"] == original["id"]
            assert row_after["email"] == original["email"]
            assert row_after["full_name"] == original["full_name"]
            assert row_after["global_role"] == original["global_role"]
            assert row_after["status"] == original["status"]
            assert row_after["password_hash"] == original["password_hash"]
    finally:
        engine.dispose()


@requires_pg
def test_bootstrap_refuses_when_existing_non_admin_matches_requested_email(pg_database_url):
    engine = create_engine(pg_database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("delete from staff_users"))
        with engine.begin() as conn:
            existing_id = conn.execute(
                text(
                    "insert into staff_users (email, full_name, global_role, status, password_hash) "
                    "values (:email, :full_name, :global_role, :status, :password_hash) "
                    "returning id"
                ),
                {
                    "email": "existing@example.com",
                    "full_name": "Existing Staff",
                    "global_role": "manager",
                    "status": "Active",
                    "password_hash": hash_password("existing-password-12345"),
                },
            ).scalar_one()

        with pytest.raises(RuntimeError) as excinfo:
            bootstrap_admin.bootstrap_administrator(
                email="  EXISTING@Example.com  ",
                full_name="Bootstrap Admin",
                password="correct-horse-battery-staple",
                database_url=pg_database_url,
            )
        assert "email already exists" in str(excinfo.value).lower()

        with engine.connect() as conn:
            rows = conn.execute(
                text("select id, email, full_name, global_role, status from staff_users")
            ).mappings().all()
            assert len(rows) == 1
            row = rows[0]
            assert row["id"] == existing_id
            assert row["email"] == "existing@example.com"
            assert row["full_name"] == "Existing Staff"
            assert row["global_role"] == "manager"
            assert row["status"] == "Active"
            admin_count = conn.execute(
                text("select count(*) from staff_users where global_role = 'administrator'")
            ).scalar_one()
            assert admin_count == 0
    finally:
        engine.dispose()


@requires_pg
def test_bootstrap_concurrent_attempts_serialized_one_succeeds_others_refused(pg_database_url):
    # Precondition: ensure no administrator exists in this disposable DB.
    engine = create_engine(pg_database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("delete from staff_users"))
    finally:
        engine.dispose()

    results = []
    errors = []
    barrier = threading.Barrier(2)

    def worker(email):
        try:
            barrier.wait(timeout=10)
            uid = bootstrap_admin.bootstrap_administrator(
                email=email,
                full_name=f"Admin {email}",
                password="correct-horse-battery-staple",
                database_url=pg_database_url,
            )
            results.append(uid)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("first@example.com",))
    t2 = threading.Thread(target=worker, args=("second@example.com",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(results) == 1
    assert len(errors) == 1
    assert "already exists" in str(errors[0]).lower()

    engine = create_engine(pg_database_url, future=True)
    try:
        with engine.connect() as conn:
            count = conn.execute(text("select count(*) from staff_users where global_role = 'administrator'")).scalar_one()
            assert count == 1
    finally:
        engine.dispose()
