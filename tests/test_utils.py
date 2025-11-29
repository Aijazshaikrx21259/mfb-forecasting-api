"""Tests for utility functions."""

import pytest
from datetime import date

from app.utils.date_helpers import (
    get_month_key,
    parse_month_key,
    get_next_month,
    get_previous_month,
)
from app.utils.validators import (
    validate_item_id,
    validate_horizon,
    sanitize_user_input,
    validate_email,
)


@pytest.mark.unit
def test_get_month_key():
    """Test month key generation."""
    dt = date(2024, 1, 15)
    assert get_month_key(dt) == "2024-01"


@pytest.mark.unit
def test_parse_month_key():
    """Test month key parsing."""
    result = parse_month_key("2024-01")
    assert result == date(2024, 1, 1)


@pytest.mark.unit
def test_get_next_month():
    """Test getting next month."""
    dt = date(2024, 1, 15)
    result = get_next_month(dt)
    assert result == date(2024, 2, 1)


@pytest.mark.unit
def test_get_previous_month():
    """Test getting previous month."""
    dt = date(2024, 2, 15)
    result = get_previous_month(dt)
    assert result == date(2024, 1, 1)


@pytest.mark.unit
def test_validate_item_id_valid():
    """Test valid item ID."""
    assert validate_item_id("P-352101") is True
    assert validate_item_id("ITEM_123") is True


@pytest.mark.unit
def test_validate_item_id_invalid():
    """Test invalid item ID."""
    assert validate_item_id("item with spaces") is False
    assert validate_item_id("item@special") is False
    assert validate_item_id("a" * 51) is False  # Too long


@pytest.mark.unit
def test_validate_horizon():
    """Test horizon validation."""
    assert validate_horizon(1) is True
    assert validate_horizon(12) is True
    assert validate_horizon(0) is False
    assert validate_horizon(13) is False


@pytest.mark.unit
def test_sanitize_user_input():
    """Test user input sanitization."""
    text = "Hello <script>alert('xss')</script> World"
    result = sanitize_user_input(text)
    assert "<" not in result
    assert ">" not in result
    assert "Hello" in result


@pytest.mark.unit
def test_validate_email():
    """Test email validation."""
    assert validate_email("user@example.com") is True
    assert validate_email("test.user@domain.co.uk") is True
    assert validate_email("invalid-email") is False
    assert validate_email("@example.com") is False
