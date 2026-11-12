"""Centralized environment-based application settings."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables and a local .env file."""

    APP_NAME: str = "POBridge API"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    FRONTEND_URL: AnyHttpUrl = "http://localhost:3000"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-6-luna"
    MAX_UPLOAD_SIZE_MB: int = Field(default=10, gt=0)
    MAX_PDF_PAGES: int = Field(default=25, gt=0)
    OPENAI_TIMEOUT_SECONDS: float = Field(default=90.0, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()


settings = get_settings()
