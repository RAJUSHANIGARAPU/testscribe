"""Application configuration — all env vars declared here."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from loguru import logger
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "TestScribe"
    app_env: Literal["development", "staging", "production"] = "development"
    app_url: str = "http://localhost:8000"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./testscribe.db"

    # JWT
    jwt_secret_key: SecretStr = Field(..., description="JWT signing secret — min 32 chars")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Anthropic
    anthropic_api_key: SecretStr = Field(..., description="Anthropic API key")
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 2000
    anthropic_timeout: float = 60.0
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: float = 60.0

    # Stripe
    stripe_secret_key: SecretStr = Field(..., description="Stripe secret key")
    stripe_publishable_key: str = Field(..., description="Stripe publishable key")
    stripe_webhook_secret: SecretStr = Field(..., description="Stripe webhook signing secret")
    stripe_price_solo: str = Field(..., description="Stripe Price ID for Solo plan")
    stripe_price_pro: str = Field(..., description="Stripe Price ID for Pro plan")
    stripe_price_team: str = Field(..., description="Stripe Price ID for Team plan")

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    # Rate limiting
    rate_limit_ip: str = "60/minute"
    rate_limit_generate: str = "20/minute"

    # Workers
    task_poll_interval: float = 2.0
    task_reaper_interval: float = 300.0

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return v.upper()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    instance = Settings()  # type: ignore[call-arg]
    logger.info(
        "Settings loaded: app_env={env} database={db} log_level={lvl}",
        env=instance.app_env,
        db=instance.database_url.split("?")[0],
        lvl=instance.log_level,
    )
    return instance


settings: Settings = get_settings()
