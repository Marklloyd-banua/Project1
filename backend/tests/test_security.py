from __future__ import annotations

from datetime import datetime, timedelta, timezone

import argon2
import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


TEST_PASSWORD = "correct-horse-battery-staple"
TEST_SUBJECT = "staff-user-123"


def _settings_claims():
    settings = get_settings()
    return settings.auth_jwt_issuer, settings.auth_jwt_audience, settings.auth_jwt_secret


def _make_token(
    *,
    sub=TEST_SUBJECT,
    iss=None,
    aud=None,
    iat=None,
    exp=None,
    secret=None,
    algorithm="HS256",
    include_sub=True,
    include_iss=True,
    include_aud=True,
    include_iat=True,
    include_exp=True,
    extra_claims=None,
):
    default_iss, default_aud, default_secret = _settings_claims()
    now = datetime.now(timezone.utc)
    payload = {}
    if include_sub:
        payload["sub"] = sub
    if include_iss:
        payload["iss"] = default_iss if iss is None else iss
    if include_aud:
        payload["aud"] = default_aud if aud is None else aud
    if include_iat:
        payload["iat"] = now if iat is None else iat
    if include_exp:
        payload["exp"] = (now + timedelta(minutes=15)) if exp is None else exp
    if extra_claims:
        payload.update(extra_claims)

    headers = {"alg": algorithm, "typ": "JWT"} if algorithm is not None else {"typ": "JWT"}
    return jwt.encode(
        payload,
        default_secret if secret is None else secret,
        algorithm=algorithm,
        headers=headers,
    )


# Password tests


def test_hash_password_verifies_correct_password():
    encoded = hash_password(TEST_PASSWORD)
    assert encoded.startswith("$argon2id$")
    assert verify_password(TEST_PASSWORD, encoded) is True


def test_verify_password_rejects_incorrect_password():
    encoded = hash_password(TEST_PASSWORD)
    assert verify_password("wrong-password-12345", encoded) is False


def test_hash_password_produces_different_salted_hashes():
    encoded_a = hash_password(TEST_PASSWORD)
    encoded_b = hash_password(TEST_PASSWORD)
    assert encoded_a != encoded_b
    assert verify_password(TEST_PASSWORD, encoded_a) is True
    assert verify_password(TEST_PASSWORD, encoded_b) is True


@pytest.mark.parametrize(
    "malformed_hash",
    [
        "",
        "not-a-hash",
        "$argon2id$v=19$m=19456,t=2,p=1$broken",
        "$argon2id$v=19$m=19456,t=2,p=1$c29tZXNhbHQ$!!!notbase64!!!",
        None,
    ],
)
def test_verify_password_fails_safely_for_malformed_hashes(malformed_hash):
    assert verify_password(TEST_PASSWORD, malformed_hash) is False  # type: ignore[arg-type]


def test_hash_password_rejects_password_shorter_than_12_characters():
    with pytest.raises(ValueError):
        hash_password("short-pass")


def test_hash_password_accepts_12_character_password():
    password = "x" * 12
    encoded = hash_password(password)
    assert verify_password(password, encoded) is True


def test_encoded_hash_fits_within_255_characters():
    encoded = hash_password(TEST_PASSWORD)
    assert len(encoded) <= 255
    # Sanity: explicit params are encoded in the hash string.
    assert "m=19456,t=2,p=1" in encoded


# JWT tests


def test_create_access_token_decodes_successfully_and_has_exact_claims():
    token = create_access_token(TEST_SUBJECT)
    payload = decode_access_token(token)

    assert set(payload.keys()) == {"sub", "iss", "aud", "iat", "exp"}
    assert payload["sub"] == TEST_SUBJECT
    iss, aud, _ = _settings_claims()
    assert payload["iss"] == iss
    assert payload["aud"] == aud
    assert isinstance(payload["iat"], int)
    assert isinstance(payload["exp"], int)
    assert payload["exp"] > payload["iat"]


def test_create_access_token_uses_configured_15_minute_lifetime():
    settings = get_settings()
    before = int(datetime.now(timezone.utc).timestamp())
    token = create_access_token(TEST_SUBJECT)
    after = int(datetime.now(timezone.utc).timestamp())
    payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
    lifetime_seconds = payload["exp"] - payload["iat"]
    assert lifetime_seconds == settings.auth_access_token_expire_minutes * 60
    assert before <= payload["iat"] <= after


@pytest.mark.parametrize("missing_claim", ["sub", "iss", "aud", "iat", "exp"])
def test_decode_access_token_rejects_missing_claims(missing_claim):
    kwargs = {f"include_{missing_claim}": False}
    token = _make_token(**kwargs)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_unexpected_claims():
    token = _make_token(extra_claims={"role": "admin"})
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_expired_tokens():
    now = datetime.now(timezone.utc)
    token = _make_token(iat=now - timedelta(minutes=20), exp=now - timedelta(minutes=1))
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_tampered_tokens():
    token = create_access_token(TEST_SUBJECT)
    header, payload, signature = token.split(".")
    # Tamper payload by flipping a character while keeping JWT structure.
    replacement = "A" if payload[0] != "A" else "B"
    tampered = f"{header}.{replacement}{payload[1:]}.{signature}"
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_decode_access_token_rejects_wrong_signing_secret():
    token = _make_token(secret="wrong-secret-value-at-least-32-chars")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_wrong_issuer():
    token = _make_token(iss="https://wrong.issuer.local")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_wrong_audience():
    token = _make_token(aud="wrong-audience")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


@pytest.mark.parametrize(
    "invalid_token",
    [
        "",
        "not-a-jwt",
        "a.b",
        "a.b.c.d",
        "abc.def.ghi",
        None,
        123,
        {"token": "nope"},
    ],
)
def test_decode_access_token_rejects_invalid_formats_and_malformed_tokens(invalid_token):
    with pytest.raises(InvalidTokenError):
        decode_access_token(invalid_token)  # type: ignore[arg-type]


def test_decode_access_token_rejects_none_algorithm_tokens():
    token = _make_token(algorithm=None)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_empty_subject():
    token = _make_token(sub="   ")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_accepts_token_within_30_second_clock_skew():
    # Token expired 20 seconds ago but within configured 30s leeway.
    now = datetime.now(timezone.utc)
    token = _make_token(iat=now - timedelta(minutes=15), exp=now - timedelta(seconds=20))
    payload = decode_access_token(token)
    assert payload["sub"] == TEST_SUBJECT


def test_decode_access_token_rejects_token_beyond_30_second_clock_skew():
    now = datetime.now(timezone.utc)
    token = _make_token(iat=now - timedelta(minutes=16), exp=now - timedelta(seconds=31))
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_invalid_token_error_does_not_expose_token_or_secret(monkeypatch):
    settings = get_settings()
    token = _make_token(secret="wrong-secret-value-at-least-32-chars")
    with pytest.raises(InvalidTokenError) as excinfo:
        decode_access_token(token)
    message = str(excinfo.value)
    assert token not in message
    assert settings.auth_jwt_secret not in message
    assert "wrong-secret-value-at-least-32-chars" not in message
