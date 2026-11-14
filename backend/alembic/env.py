"""Alembic environment (Phase 2).

Wiring: resolves the database URL from application configuration and exposes
`target_metadata` = the SQLAlchemy DeclarativeBase metadata (all 19 Phase 2
tables). The hand-written migrations (0001..0004) are the authoritative DDL;
metadata exists for autogenerate parity checks only.
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

# Phase 2: assign the SQLAlchemy 2.x DeclarativeBase metadata. Importing the
# models package registers all 19 tables on Base.metadata. The hand-written
# migrations remain the AUTHORITATIVE DDL; metadata is for autogenerate
# parity checks only.
from app.models import Base

target_metadata = Base.metadata


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
