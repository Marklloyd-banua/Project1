"""Alembic environment (Phase 1 scaffold).

Wiring only: resolves the database URL from application configuration and exposes
`target_metadata` (empty until Phase 2 introduces models). No migrations exist yet.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the application-configured URL (SQLite dev default / PostgreSQL via DATABASE_URL).
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Phase 2 will assign the SQLAlchemy 2.x DeclarativeBase metadata here.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
