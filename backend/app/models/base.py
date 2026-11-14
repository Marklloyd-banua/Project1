"""Shared declarative base, naming conventions, and column mixins (Phase 2).

Model metadata is portable DDL (SQLite + PostgreSQL). The hand-written Alembic
migrations are the AUTHORITATIVE PostgreSQL DDL; where PostgreSQL-only features
are used (column-list ``ON DELETE SET NULL (col)``, regex CHECKs with ``~``,
the counter-initializing trigger, ``gen_random_uuid()`` server defaults), the
migration carries them and this metadata carries the portable equivalent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all Phase 2 models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UuidPk:
    """UUID primary key named ``id`` (Python-generated; PG migrations add
    ``gen_random_uuid()`` as the server-side default)."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Timestamped:
    """``created_at``/``updated_at`` timestamp columns (server defaulted)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
