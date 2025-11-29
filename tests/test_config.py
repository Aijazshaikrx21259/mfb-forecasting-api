"""Tests for configuration management."""

import os
import pytest
from unittest.mock import patch

from app.config import get_settings, _split_csv, _parse_bool


@pytest.mark.unit
def test_split_csv_empty():
    """Test CSV splitting with empty string."""
    assert _split_csv("") == []
    assert _split_csv(None) == []


@pytest.mark.unit
def test_split_csv_single_value():
    """Test CSV splitting with single value."""
    assert _split_csv("value1") == ["value1"]


@pytest.mark.unit
def test_split_csv_multiple_values():
    """Test CSV splitting with multiple values."""
    assert _split_csv("value1,value2,value3") == ["value1", "value2", "value3"]


@pytest.mark.unit
def test_split_csv_with_spaces():
    """Test CSV splitting trims whitespace."""
    assert _split_csv(" value1 , value2 , value3 ") == ["value1", "value2", "value3"]


@pytest.mark.unit
def test_parse_bool_true_values():
    """Test boolean parsing for true values."""
    assert _parse_bool("1", False) is True
    assert _parse_bool("true", False) is True
    assert _parse_bool("TRUE", False) is True
    assert _parse_bool("yes", False) is True
    assert _parse_bool("y", False) is True
    assert _parse_bool("on", False) is True


@pytest.mark.unit
def test_parse_bool_false_values():
    """Test boolean parsing for false values."""
    assert _parse_bool("0", True) is False
    assert _parse_bool("false", True) is False
    assert _parse_bool("no", True) is False
    assert _parse_bool("off", True) is False


@pytest.mark.unit
def test_parse_bool_default():
    """Test boolean parsing returns default for None."""
    assert _parse_bool(None, True) is True
    assert _parse_bool(None, False) is False


@pytest.mark.unit
def test_get_settings_local_environment():
    """Test settings for local environment."""
    with patch.dict(os.environ, {"ENVIRONMENT": "local"}, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.environment == "local"
        assert settings.allow_all_origins is True


@pytest.mark.unit
def test_get_settings_production_requires_origins():
    """Test that production environment requires ALLOWED_ORIGINS."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS must be set"):
            get_settings()


@pytest.mark.unit
def test_get_settings_production_with_origins():
    """Test settings for production environment with origins."""
    with patch.dict(
        os.environ,
        {
            "ENVIRONMENT": "production",
            "ALLOWED_ORIGINS": "https://example.com,https://app.example.com",
        },
        clear=True,
    ):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.environment == "production"
        assert settings.allow_all_origins is False
        assert "https://example.com" in settings.allowed_origins


@pytest.mark.unit
def test_get_settings_pipeline_intervals():
    """Test pipeline interval configuration."""
    with patch.dict(
        os.environ,
        {
            "PIPELINE_INTERVAL_MINUTES": "720",
            "PIPELINE_INITIAL_DELAY_SECONDS": "30",
        },
        clear=False,
    ):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.pipeline_interval_minutes == 720
        assert settings.pipeline_initial_delay_seconds == 30


@pytest.mark.unit
def test_get_settings_invalid_intervals_use_defaults():
    """Test that invalid interval values fall back to defaults."""
    with patch.dict(
        os.environ,
        {
            "PIPELINE_INTERVAL_MINUTES": "invalid",
            "PIPELINE_INITIAL_DELAY_SECONDS": "invalid",
        },
        clear=False,
    ):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.pipeline_interval_minutes == 1440
        assert settings.pipeline_initial_delay_seconds == 60
