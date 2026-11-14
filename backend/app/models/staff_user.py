"""staff_users model (migration 0001) — global platform staff identities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UuidPk


class StaffUser(Base, UuidPk, Timestamped):
    __tablename__ = "staff_users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable from day one: Phase 3 (auth) sets it on signup.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    global_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer", server_default="viewer"
    )
    # Free-form on purpose (mirrors dashboard EntityStatus vocabulary; M1 hardening deferred).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Active", server_default="Active"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "email = lower(email)", name="email_lowercase"
        ),
        CheckConstraint(
            "length(password_hash) <= 255", name="password_hash_length"
        ),
        CheckConstraint(
            "global_role IN ('administrator','manager','viewer')",
            name="global_role_vocabulary",
        ),
    )
