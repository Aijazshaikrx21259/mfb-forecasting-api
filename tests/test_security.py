"""Tests for security and authentication."""

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from app.security import verify_api_key
from app.config import Settings


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_api_key_no_key_configured():
    """Test that verification passes when no API key is configured."""
    # Should not raise exception when api_key is None
    await verify_api_key(api_key=None)
    await verify_api_key(api_key="any-key")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_api_key_valid_key(monkeypatch):
    """Test that verification passes with valid API key."""
    # Mock settings to return a configured API key
    mock_settings = MagicMock()
    mock_settings.api_key = "secret-key"
    
    from app import security
    monkeypatch.setattr(security, "get_settings", lambda: mock_settings)
    
    # Should not raise exception
    await security.verify_api_key(api_key="secret-key")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_api_key_invalid_key(monkeypatch):
    """Test that verification fails with invalid API key."""
    mock_settings = MagicMock()
    mock_settings.api_key = "secret-key"
    
    from app import security
    monkeypatch.setattr(security, "get_settings", lambda: mock_settings)
    
    # Should raise HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await security.verify_api_key(api_key="wrong-key")
    
    assert exc_info.value.status_code == 401


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_api_key_missing_key(monkeypatch):
    """Test that verification fails when key is required but not provided."""
    mock_settings = MagicMock()
    mock_settings.api_key = "secret-key"
    
    from app import security
    monkeypatch.setattr(security, "get_settings", lambda: mock_settings)
    
    # Should raise HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await security.verify_api_key(api_key=None)
    
    assert exc_info.value.status_code == 401
