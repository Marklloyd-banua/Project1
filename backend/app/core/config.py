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

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
