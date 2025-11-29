"""Pytest configuration and shared fixtures."""

import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import asyncpg
from fastapi.testclient import TestClient

from app.main import create_application
from app.config import Settings


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        environment="test",
        api_key="test-api-key",
        allowed_origins=["http://testserver"],
        allow_all_origins=True,
        database_url=None,
        pipeline_auto_run=False,
        pipeline_run_on_demand=False,
        pipeline_interval_minutes=1440,
        pipeline_initial_delay_seconds=0,
        pipeline_stable_interval_minutes=None,
        pipeline_volatile_interval_minutes=None,
    )


@pytest.fixture
def mock_db_pool() -> AsyncMock:
    """Create a mock database pool."""
    pool = AsyncMock(spec=asyncpg.Pool)
    connection = AsyncMock(spec=asyncpg.Connection)
    pool.acquire.return_value.__aenter__.return_value = connection
    return pool


@pytest.fixture
def mock_db_connection() -> AsyncMock:
    """Create a mock database connection."""
    return AsyncMock(spec=asyncpg.Connection)


@pytest.fixture
def test_client() -> TestClient:
    """Create a test client for the FastAPI application."""
    app = create_application()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    """Return headers with test API key."""
    return {"X-API-Key": "test-api-key"}
