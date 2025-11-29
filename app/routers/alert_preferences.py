"""Alert preferences management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
import asyncpg

from app.db import get_db_connection
from app.security import verify_api_key
from app.models.alerts import (
    AlertPreferencesResponse,
    AlertPreferencesUpdate,
)
from app.services.alert_service import AlertService


router = APIRouter(
    prefix="/api/alert-preferences",
    tags=["alert-preferences"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("", response_model=AlertPreferencesResponse)
async def get_preferences(
    user_id: Annotated[str, Query(description="User ID")],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertPreferencesResponse:
    """
    Get alert preferences for a user.
    
    If preferences don't exist, returns default preferences.
    
    - **user_id**: User identifier
    """
    service = AlertService(conn)
    preferences = await service.get_preferences(user_id)
    
    if not preferences:
        # Return default preferences
        from app.models.alerts import AlertType, AlertPriority
        from datetime import datetime
        
        preferences = AlertPreferencesResponse(
            user_id=user_id,
            enabled_alert_types=[
                AlertType.FORECAST_READY,
                AlertType.HIGH_DEMAND_SPIKE,
                AlertType.STOCKOUT_RISK,
                AlertType.HIGH_PRIORITY_ITEMS,
            ],
            min_priority=AlertPriority.MEDIUM,
            weekly_digest_enabled=True,
            weekly_digest_day=1,  # Monday
            in_app_enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    
    return preferences


@router.put("", response_model=AlertPreferencesResponse)
async def update_preferences(
    user_id: Annotated[str, Query(description="User ID")],
    preferences: AlertPreferencesUpdate,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertPreferencesResponse:
    """
    Update alert preferences for a user.
    
    Creates preferences if they don't exist.
    
    - **user_id**: User identifier
    - **enabled_alert_types**: List of alert types to receive
    - **min_priority**: Minimum priority level to show
    - **weekly_digest_enabled**: Enable/disable weekly digest
    - **weekly_digest_day**: Day of week for digest (1=Monday, 7=Sunday)
    - **in_app_enabled**: Enable/disable in-app notifications
    """
    service = AlertService(conn)
    return await service.update_preferences(user_id, preferences)


@router.post("/reset", response_model=AlertPreferencesResponse)
async def reset_preferences(
    user_id: Annotated[str, Query(description="User ID")],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertPreferencesResponse:
    """
    Reset alert preferences to defaults for a user.
    
    - **user_id**: User identifier
    """
    from app.models.alerts import AlertType, AlertPriority
    
    service = AlertService(conn)
    
    default_preferences = AlertPreferencesUpdate(
        enabled_alert_types=[
            AlertType.FORECAST_READY,
            AlertType.HIGH_DEMAND_SPIKE,
            AlertType.STOCKOUT_RISK,
            AlertType.HIGH_PRIORITY_ITEMS,
        ],
        min_priority=AlertPriority.MEDIUM,
        weekly_digest_enabled=True,
        weekly_digest_day=1,
        in_app_enabled=True,
    )
    
    return await service.update_preferences(user_id, default_preferences)
