import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults_are_safe_for_local_dev():
    settings = Settings(_env_file=None)
    assert settings.app_name == "saas-admin-backend"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.app_env == "development"
    assert settings.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_api_v1_prefix_normalized():
    settings = Settings(API_V1_PREFIX="api/v2/", _env_file=None)
    assert settings.api_v1_prefix == "/api/v2"


def test_cors_origins_must_not_be_empty():
    with pytest.raises(ValidationError):
        Settings(CORS_ORIGINS="   ", _env_file=None)


def test_cors_origin_list_parses_csv():
    settings = Settings(CORS_ORIGINS="https://app.example.com, http://localhost:5173", _env_file=None)
    assert settings.cors_origin_list == ["https://app.example.com", "http://localhost:5173"]
