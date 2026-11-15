from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables (placeholders in .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="saas-admin-backend", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    debug: bool = Field(default=False, alias="DEBUG")
    # Comma-separated origins, e.g. http://localhost:5173,https://app.example.com
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS")
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")
    # SQLAlchemy database URL. SQLite default keeps Termux/local dev dependency-free.
    # PostgreSQL example: postgresql+pg8000://user:password@host:5432/dbname
    # NEVER commit real credentials; production values belong in backend/.env (git-ignored).
    database_url: str = Field(default="sqlite:///./dev.db", alias="DATABASE_URL")

    # B1 (approved, config-only): JWT auth settings. Required for startup/config validation.
    # Use strong, environment-specific, non-committed values. CI/tests must use test-only values.
    auth_jwt_secret: str = Field(alias="AUTH_JWT_SECRET")
    auth_jwt_issuer: str = Field(alias="AUTH_JWT_ISSUER")
    auth_jwt_audience: str = Field(alias="AUTH_JWT_AUDIENCE")
    auth_access_token_expire_minutes: int = Field(default=15, alias="AUTH_ACCESS_TOKEN_EXPIRE_MINUTES")

    @field_validator("api_v1_prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        prefix = value.strip() or "/api/v1"
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return prefix.rstrip("/") or "/api/v1"

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        # Keep as string; parsed by `cors_origin_list`. Validate non-empty for safety.
        if not value or not value.strip():
            raise ValueError("CORS_ORIGINS must not be empty")
        return value

    @field_validator("auth_jwt_secret")
    @classmethod
    def validate_auth_jwt_secret(cls, value: str) -> str:
        secret = value.strip()
        # Enforce the minimum UTF-8 byte length. Production secrets must be
        # generated using a cryptographically secure random source.
        # Test/CI environments must provide explicit non-production test-only values meeting this rule.
        # Enforce minimum length in UTF-8 bytes (not characters) without exposing the secret value.
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("AUTH_JWT_SECRET must be at least 32 UTF-8 bytes")
        return secret

    @field_validator("auth_jwt_issuer", "auth_jwt_audience")
    @classmethod
    def validate_auth_jwt_non_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("auth_access_token_expire_minutes")
    @classmethod
    def validate_auth_access_token_expire_minutes(cls, value: int) -> int:
        # Approved B1 default is 15 minutes; enforce bounded, sensible values.
        if value < 1 or value > 60:
            raise ValueError("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 60")
        return value

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
