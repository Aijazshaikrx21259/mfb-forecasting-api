"""Configuration utilities for the application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    environment: str
    api_key: str | None
    allowed_origins: list[str]
    allow_all_origins: bool
    database_url: str | None
    pipeline_auto_run: bool
    pipeline_run_on_demand: bool
    pipeline_interval_minutes: int
    pipeline_initial_delay_seconds: int
    pipeline_stable_interval_minutes: int | None
    pipeline_volatile_interval_minutes: int | None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    environment = os.getenv("ENVIRONMENT", "local")
    api_key = os.getenv("API_KEY")
    database_url = os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
    allowed_origins_env = _split_csv(os.getenv("ALLOWED_ORIGINS"))
    env_lower = environment.lower()

    pipeline_auto_run = _parse_bool(os.getenv("PIPELINE_AUTO_RUN"), default=False)
    pipeline_run_on_demand = _parse_bool(
        os.getenv("PIPELINE_RUN_ON_DEMAND"), default=True
    )
    try:
        pipeline_interval_minutes = int(os.getenv("PIPELINE_INTERVAL_MINUTES", "1440"))
    except ValueError:
        pipeline_interval_minutes = 1440
    try:
        pipeline_initial_delay_seconds = int(os.getenv("PIPELINE_INITIAL_DELAY_SECONDS", "60"))
    except ValueError:
        pipeline_initial_delay_seconds = 60
    
    # Segmented pipeline intervals for stable vs volatile items
    pipeline_stable_interval_minutes = None
    pipeline_volatile_interval_minutes = None
    stable_env = os.getenv("PIPELINE_STABLE_INTERVAL_MINUTES")
    volatile_env = os.getenv("PIPELINE_VOLATILE_INTERVAL_MINUTES")
    if stable_env:
        try:
            pipeline_stable_interval_minutes = int(stable_env)
        except ValueError:
            pass
    if volatile_env:
        try:
            pipeline_volatile_interval_minutes = int(volatile_env)
        except ValueError:
            pass

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
        database_url=database_url,
        pipeline_auto_run=pipeline_auto_run,
        pipeline_run_on_demand=pipeline_run_on_demand,
        pipeline_interval_minutes=max(pipeline_interval_minutes, 1),
        pipeline_initial_delay_seconds=max(pipeline_initial_delay_seconds, 0),
        pipeline_stable_interval_minutes=pipeline_stable_interval_minutes,
        pipeline_volatile_interval_minutes=pipeline_volatile_interval_minutes,
    )
