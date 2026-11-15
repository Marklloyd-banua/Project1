import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


# B1.1 config-only: required auth settings must be supplied explicitly in tests (non-production).
TEST_AUTH_SETTINGS = {
    "AUTH_JWT_SECRET": "test-only-jwt-secret-value-at-least-32-chars",
    "AUTH_JWT_ISSUER": "https://test.issuer.local",
    "AUTH_JWT_AUDIENCE": "northstar-test-audience",
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": 15,
}


def make_settings(**overrides) -> Settings:
    data = {**TEST_AUTH_SETTINGS, **overrides}
    return Settings(_env_file=None, **data)


def test_settings_defaults_are_safe_for_local_dev():
    settings = make_settings()
    assert settings.app_name == "saas-admin-backend"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.app_env == "development"
    assert settings.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_api_v1_prefix_normalized():
    settings = make_settings(API_V1_PREFIX="api/v2/")
    assert settings.api_v1_prefix == "/api/v2"


def test_cors_origins_must_not_be_empty():
    with pytest.raises(ValidationError):
        make_settings(CORS_ORIGINS="   ")


def test_cors_origin_list_parses_csv():
    settings = make_settings(CORS_ORIGINS="https://app.example.com, http://localhost:5173")
    assert settings.cors_origin_list == ["https://app.example.com", "http://localhost:5173"]


def test_auth_settings_required_and_default_ttl():
    settings = make_settings()
    assert settings.auth_jwt_secret == TEST_AUTH_SETTINGS["AUTH_JWT_SECRET"]
    assert settings.auth_jwt_issuer == TEST_AUTH_SETTINGS["AUTH_JWT_ISSUER"]
    assert settings.auth_jwt_audience == TEST_AUTH_SETTINGS["AUTH_JWT_AUDIENCE"]
    assert settings.auth_access_token_expire_minutes == 15


def test_auth_jwt_secret_rejected_when_fewer_than_32_utf8_bytes():
    # 10 Unicode snowmen = 30 UTF-8 bytes (< 32) though 10 characters.
    short_multibyte = "☃" * 10
    assert len(short_multibyte.encode("utf-8")) < 32
    with pytest.raises(ValidationError):
        make_settings(AUTH_JWT_SECRET=short_multibyte)


def test_auth_jwt_secret_accepted_when_at_least_32_utf8_bytes():
    # 11 Unicode snowmen = 33 UTF-8 bytes (>= 32), exercises byte-based validation.
    valid_multibyte = "☃" * 11
    assert len(valid_multibyte.encode("utf-8")) >= 32
    settings = make_settings(AUTH_JWT_SECRET=valid_multibyte)
    assert settings.auth_jwt_secret == valid_multibyte


def test_auth_jwt_issuer_and_audience_required():
    with pytest.raises(ValidationError):
        make_settings(AUTH_JWT_ISSUER="   ")
    with pytest.raises(ValidationError):
        make_settings(AUTH_JWT_AUDIENCE="   ")


@pytest.mark.parametrize("ttl", [0, -1, 61, 120])
def test_auth_access_token_expire_minutes_bounds(ttl):
    with pytest.raises(ValidationError):
        make_settings(AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=ttl)


def test_test_auth_env_available_before_application_imports_during_collection():
    # Conftest forces deterministic non-production auth env at import time (before collection-time imports).
    assert os.environ.get("AUTH_JWT_SECRET")
    assert os.environ.get("AUTH_JWT_ISSUER")
    assert os.environ.get("AUTH_JWT_AUDIENCE")
    assert os.environ.get("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES") == "15"

    # Safe checks: clear cached settings and verify application/config access without
    # purging or reloading application modules (avoids disrupting other tests).
    get_settings.cache_clear()

    from app.core.db import build_engine
    from app.main import create_app

    settings = get_settings()
    assert settings.auth_access_token_expire_minutes == 15
    assert create_app().title == settings.app_name
    probe_engine = build_engine()
    probe_engine.dispose()


def test_settings_cache_isolated_between_tests(monkeypatch):
    from app.core.config import get_settings as cached_get_settings

    cached_get_settings.cache_clear()
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://cache-isolation-a.test")
    first = cached_get_settings()
    second = cached_get_settings()
    assert first is second
    assert first.auth_jwt_issuer == "https://cache-isolation-a.test"

    # Simulate next-test isolation behavior: cache cleared and env restored/changed.
    cached_get_settings.cache_clear()
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://cache-isolation-b.test")
    third = cached_get_settings()
    assert third is not first
    assert third.auth_jwt_issuer == "https://cache-isolation-b.test"
