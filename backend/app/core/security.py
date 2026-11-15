"""Password hashing and JWT primitives for Northstar backend (B1.2).

These are security primitives only: no login endpoints, no /auth/me, no refresh
tokens, no revocation, no database access, and no authorization logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import argon2
import jwt

from app.core.config import get_settings


_MIN_PASSWORD_LENGTH = 12
_MAX_STAFF_PASSWORD_HASH_LENGTH = 255
_JWT_ALGORITHM = "HS256"
_JWT_CLOCK_SKEW_SECONDS = 30
_REQUIRED_JWT_CLAIMS = frozenset({"sub", "iss", "aud", "iat", "exp"})


class InvalidTokenError(Exception):
    """Generic invalid-token error. Intentionally contains no token or secret details."""


_password_hasher = argon2.PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=argon2.Type.ID,
)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id with explicit B1.2 parameters.

    Raises ValueError if the password is shorter than 12 characters or if the
    resulting encoded hash would exceed the staff_users.password_hash limit.
    """
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError("Password must be at least 12 characters")

    encoded_hash = _password_hasher.hash(password)
    if len(encoded_hash) > _MAX_STAFF_PASSWORD_HASH_LENGTH:
        raise ValueError("Encoded password hash exceeds staff_users.password_hash limit")
    return encoded_hash


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password against an encoded Argon2 hash.

    Returns False for incorrect passwords and for malformed/unverifiable stored
    hashes. Internal Argon2 exceptions are not exposed.
    """
    try:
        return _password_hasher.verify(encoded_hash, password)
    except Exception:
        return False


def create_access_token(subject: str) -> str:
    """Create an HS256 access token with the exact B1.2 claims."""
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string")

    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.auth_access_token_expire_minutes)
    payload = {
        "sub": subject,
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an HS256 access token.

    Validation is strict and rejects missing/unexpected/malformed/expired/tampered,
    incorrectly signed, wrong-issuer, and wrong-audience tokens. The allowed
    algorithm is fixed to HS256 and is never taken from the token header.
    Raises InvalidTokenError without disclosing token contents, secrets, or
    internal validation details.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[_JWT_ALGORITHM],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            leeway=timedelta(seconds=_JWT_CLOCK_SKEW_SECONDS),
            options={
                "require": sorted(_REQUIRED_JWT_CLAIMS),
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except Exception:
        raise InvalidTokenError("Invalid token") from None

    if not isinstance(payload, dict):
        raise InvalidTokenError("Invalid token")

    if set(payload.keys()) != _REQUIRED_JWT_CLAIMS:
        raise InvalidTokenError("Invalid token")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise InvalidTokenError("Invalid token")

    return payload
