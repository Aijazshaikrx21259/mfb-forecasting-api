"""Configuration utilities for the application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    environment: str
    api_key: str | None
    allowed_origins: list[str]
    allow_all_origins: bool


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    environment = os.getenv("ENVIRONMENT", "local")
    api_key = os.getenv("API_KEY")
    allowed_origins_env = _split_csv(os.getenv("ALLOWED_ORIGINS"))
    env_lower = environment.lower()

    if env_lower == "production":
        if not allowed_origins_env:
            raise RuntimeError(
                "ALLOWED_ORIGINS must be set in production to whitelist trusted frontends."
            )
        allowed_origins = allowed_origins_env
        allow_all_origins = False
    else:
        allowed_origins = allowed_origins_env or ["*"]
        allow_all_origins = True

    return Settings(
        environment=environment,
        api_key=api_key,
        allowed_origins=allowed_origins,
        allow_all_origins=allow_all_origins,
    )


