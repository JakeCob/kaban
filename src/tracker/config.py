"""Application settings, loaded from environment variables via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    api_key: str = Field(alias="API_KEY")

    metagross_base_url: str = Field(alias="METAGROSS_BASE_URL")
    metagross_token: str = Field(alias="METAGROSS_TOKEN")

    apify_token: str = Field(alias="APIFY_TOKEN")
    firecrawl_api_key: str | None = Field(default=None, alias="FIRECRAWL_API_KEY")
    n8n_webhook_url: str | None = Field(default=None, alias="N8N_WEBHOOK_URL")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
