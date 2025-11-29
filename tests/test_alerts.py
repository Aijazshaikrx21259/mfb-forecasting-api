"""Tests for alert system."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from app.models.alerts import (
    AlertCreate,
    AlertType,
    AlertPriority,
    AlertStatus,
    AlertPreferencesUpdate,
)
from app.services.alert_service import AlertService


@pytest.fixture
def mock_alert_row():
    """Create a mock alert database row."""
    alert_id = uuid4()
    return {
        "alert_id": alert_id,
        "user_id": "user123",
        "alert_type": "FORECAST_READY",
        "priority": "MEDIUM",
        "status": "UNREAD",
        "title": "New Forecast Available",
        "message": "Forecast run completed successfully.",
        "metadata": {"run_id": "abc123"},
        "action_url": "/items",
        "action_label": "View Forecast",
        "created_at": datetime.utcnow(),
        "read_at": None,
        "dismissed_at": None,
        "expires_at": datetime.utcnow() + timedelta(days=7),
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_alert(mock_db_connection, mock_alert_row):
    """Test creating a new alert."""
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_alert_row)
    
    service = AlertService(mock_db_connection)
    alert_create = AlertCreate(
        user_id="user123",
        alert_type=AlertType.FORECAST_READY,
        priority=AlertPriority.MEDIUM,
        title="New Forecast Available",
        message="Forecast run completed successfully.",
        metadata={"run_id": "abc123"},
        action_url="/items",
        action_label="View Forecast",
        expires_hours=168,
    )
    
    result = await service.create_alert(alert_create)
    
    assert result.user_id == "user123"
    assert result.alert_type == AlertType.FORECAST_READY
    assert result.status == AlertStatus.UNREAD
    assert mock_db_connection.fetchrow.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_alert(mock_db_connection, mock_alert_row):
    """Test retrieving a specific alert."""
    alert_id = mock_alert_row["alert_id"]
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_alert_row)
    
    service = AlertService(mock_db_connection)
    result = await service.get_alert(alert_id, "user123")
    
    assert result is not None
    assert result.alert_id == alert_id
    assert result.user_id == "user123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_alert_not_found(mock_db_connection):
    """Test retrieving a non-existent alert."""
    mock_db_connection.fetchrow = AsyncMock(return_value=None)
    
    service = AlertService(mock_db_connection)
    result = await service.get_alert(uuid4(), "user123")
    
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_alerts(mock_db_connection, mock_alert_row):
    """Test listing alerts with pagination."""
    mock_db_connection.fetchval = AsyncMock(return_value=10)
    mock_db_connection.fetch = AsyncMock(return_value=[mock_alert_row])
    
    service = AlertService(mock_db_connection)
    alerts, total = await service.list_alerts(
        user_id="user123",
        limit=5,
        offset=0,
    )
    
    assert len(alerts) == 1
    assert total == 10
    assert alerts[0].user_id == "user123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_alert_status(mock_db_connection, mock_alert_row):
    """Test updating alert status to READ."""
    mock_alert_row["status"] = "READ"
    mock_alert_row["read_at"] = datetime.utcnow()
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_alert_row)
    
    service = AlertService(mock_db_connection)
    result = await service.update_alert_status(
        alert_id=mock_alert_row["alert_id"],
        user_id="user123",
        status=AlertStatus.READ,
    )
    
    assert result is not None
    assert result.status == AlertStatus.READ
    assert result.read_at is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mark_all_as_read(mock_db_connection):
    """Test marking all alerts as read."""
    mock_db_connection.execute = AsyncMock(return_value="UPDATE 5")
    
    service = AlertService(mock_db_connection)
    count = await service.mark_all_as_read("user123")
    
    assert count == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_alert(mock_db_connection):
    """Test deleting an alert."""
    mock_db_connection.execute = AsyncMock(return_value="DELETE 1")
    
    service = AlertService(mock_db_connection)
    result = await service.delete_alert(uuid4(), "user123")
    
    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_unread_count(mock_db_connection):
    """Test getting unread alert count."""
    mock_db_connection.fetchval = AsyncMock(return_value=3)
    
    service = AlertService(mock_db_connection)
    count = await service.get_unread_count("user123")
    
    assert count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_preferences(mock_db_connection):
    """Test updating alert preferences."""
    mock_prefs_row = {
        "user_id": "user123",
        "enabled_alert_types": ["FORECAST_READY", "STOCKOUT_RISK"],
        "min_priority": "HIGH",
        "weekly_digest_enabled": False,
        "weekly_digest_day": 1,
        "in_app_enabled": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_prefs_row)
    
    service = AlertService(mock_db_connection)
    preferences_update = AlertPreferencesUpdate(
        enabled_alert_types=[AlertType.FORECAST_READY, AlertType.STOCKOUT_RISK],
        min_priority=AlertPriority.HIGH,
        weekly_digest_enabled=False,
    )
    
    result = await service.update_preferences("user123", preferences_update)
    
    assert result.user_id == "user123"
    assert result.min_priority == AlertPriority.HIGH
    assert result.weekly_digest_enabled is False


@pytest.mark.unit
def test_alert_create_validation():
    """Test AlertCreate model validation."""
    # Valid alert
    alert = AlertCreate(
        user_id="user123",
        alert_type=AlertType.FORECAST_READY,
        title="Test Alert",
        message="Test message",
    )
    assert alert.priority == AlertPriority.MEDIUM  # Default
    
    # Test title length validation
    with pytest.raises(ValueError):
        AlertCreate(
            user_id="user123",
            alert_type=AlertType.FORECAST_READY,
            title="",  # Empty title
            message="Test message",
        )


@pytest.mark.unit
def test_alert_type_enum():
    """Test AlertType enum values."""
    assert AlertType.FORECAST_READY.value == "FORECAST_READY"
    assert AlertType.STOCKOUT_RISK.value == "STOCKOUT_RISK"
    assert len(AlertType) == 9  # Total alert types


@pytest.mark.unit
def test_alert_priority_enum():
    """Test AlertPriority enum values."""
    assert AlertPriority.LOW.value == "LOW"
    assert AlertPriority.CRITICAL.value == "CRITICAL"
    assert len(AlertPriority) == 4


@pytest.mark.unit
def test_alert_status_enum():
    """Test AlertStatus enum values."""
    assert AlertStatus.UNREAD.value == "UNREAD"
    assert AlertStatus.ARCHIVED.value == "ARCHIVED"
    assert len(AlertStatus) == 4
