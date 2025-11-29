"""Pydantic models for alert system."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AlertType(str, Enum):
    """Alert type enumeration."""

    FORECAST_READY = "FORECAST_READY"
    HIGH_DEMAND_SPIKE = "HIGH_DEMAND_SPIKE"
    LOW_DEMAND_DROP = "LOW_DEMAND_DROP"
    STOCKOUT_RISK = "STOCKOUT_RISK"
    HIGH_PRIORITY_ITEMS = "HIGH_PRIORITY_ITEMS"
    MODEL_PERFORMANCE_ALERT = "MODEL_PERFORMANCE_ALERT"
    DATA_QUALITY_ISSUE = "DATA_QUALITY_ISSUE"
    PIPELINE_FAILURE = "PIPELINE_FAILURE"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"


class AlertPriority(str, Enum):
    """Alert priority enumeration."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    """Alert status enumeration."""

    UNREAD = "UNREAD"
    READ = "READ"
    DISMISSED = "DISMISSED"
    ARCHIVED = "ARCHIVED"


class AlertCreate(BaseModel):
    """Request model for creating an alert."""

    user_id: str = Field(..., description="User ID (Clerk ID or email)")
    alert_type: AlertType
    priority: AlertPriority = AlertPriority.MEDIUM
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=1000)
    metadata: dict[str, Any] | None = None
    action_url: str | None = Field(None, max_length=500)
    action_label: str | None = Field(None, max_length=50)
    expires_hours: int | None = Field(None, ge=1, le=8760, description="Hours until expiration (max 1 year)")

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Ensure metadata is a valid JSON-serializable dict."""
        if v is None:
            return v
        # Basic validation - could be expanded
        if not isinstance(v, dict):
            raise ValueError("metadata must be a dictionary")
        return v


class AlertResponse(BaseModel):
    """Response model for alert data."""

    alert_id: UUID
    user_id: str
    alert_type: AlertType
    priority: AlertPriority
    status: AlertStatus
    title: str
    message: str
    metadata: dict[str, Any] | None
    action_url: str | None
    action_label: str | None
    created_at: datetime
    read_at: datetime | None
    dismissed_at: datetime | None
    expires_at: datetime | None

    class Config:
        from_attributes = True


class AlertUpdate(BaseModel):
    """Request model for updating an alert."""

    status: AlertStatus | None = None


class AlertPreferencesResponse(BaseModel):
    """Response model for user alert preferences."""

    user_id: str
    enabled_alert_types: list[AlertType]
    min_priority: AlertPriority
    weekly_digest_enabled: bool
    weekly_digest_day: int = Field(..., ge=1, le=7, description="1=Monday, 7=Sunday")
    in_app_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlertPreferencesUpdate(BaseModel):
    """Request model for updating alert preferences."""

    enabled_alert_types: list[AlertType] | None = None
    min_priority: AlertPriority | None = None
    weekly_digest_enabled: bool | None = None
    weekly_digest_day: int | None = Field(None, ge=1, le=7)
    in_app_enabled: bool | None = None


class AlertListResponse(BaseModel):
    """Response model for paginated alert list."""

    alerts: list[AlertResponse]
    total: int
    page: int
    page_size: int
    unread_count: int


class AlertStatsResponse(BaseModel):
    """Response model for alert statistics."""

    total_alerts: int
    unread_count: int
    by_priority: dict[str, int]
    by_type: dict[str, int]
    recent_alerts: list[AlertResponse]
