"""Async database connection management for the FastAPI application."""

from __future__ import annotations

import logging
from typing import AsyncIterator

import asyncpg  # type: ignore[import-untyped]
from fastapi import HTTPException, status  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_POOL: asyncpg.Pool | None = None


async def init_db_pool(database_url: str | None) -> None:
    """Initialise the asyncpg connection pool if configuration is provided."""

    global _POOL  # noqa: PLW0603

    if not database_url:
        logger.warning(
            "DATABASE_URL is not configured; database-backed endpoints will be unavailable."
        )
        return

    if _POOL is not None:
        return

    logger.info("Creating asyncpg connection pool for %s", database_url)
    _POOL = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=20,
        command_timeout=60,  # Increased from 30 to 60 seconds
        timeout=30,  # Connection acquisition timeout
        max_queries=50000,  # Max queries per connection before recycling
        max_inactive_connection_lifetime=300,  # 5 minutes
    )


async def close_db_pool() -> None:
    """Close the asyncpg connection pool if it has been initialised."""

    global _POOL  # noqa: PLW0603

    if _POOL is None:
        return

    logger.info("Closing asyncpg connection pool")
    await _POOL.close()
    _POOL = None


async def _get_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool is not initialised.",
        )
    return _POOL


async def get_db_connection() -> AsyncIterator[asyncpg.Connection]:
    """Yield a pooled database connection for request-scoped usage."""

    pool = await _get_pool()
    async with pool.acquire() as connection:
        yield connection


async def get_db_pool() -> asyncpg.Pool:
    """Return the shared asyncpg connection pool."""

    return await _get_pool()


__all__ = [
    "init_db_pool",
    "close_db_pool",
    "get_db_connection",
    "get_db_pool",
]
