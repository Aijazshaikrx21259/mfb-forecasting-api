"""Alert management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
import asyncpg

from app.db import get_db_connection
from app.security import verify_api_key
from app.models.alerts import (
    AlertCreate,
    AlertResponse,
    AlertUpdate,
    AlertListResponse,
    AlertStatsResponse,
    AlertType,
    AlertPriority,
    AlertStatus,
)
from app.services.alert_service import AlertService


router = APIRouter(
    prefix="/api/alerts",
    tags=["alerts"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    alert: AlertCreate,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertResponse:
    """
    Create a new alert for a user.
    
    - **user_id**: User identifier (Clerk ID or email)
    - **alert_type**: Type of alert
    - **priority**: Alert priority level
    - **title**: Alert title (max 200 chars)
    - **message**: Alert message (max 1000 chars)
    - **metadata**: Optional JSON metadata
    - **action_url**: Optional deep link URL
    - **action_label**: Optional button text
    - **expires_hours**: Hours until alert expires (default: 7 days)
    """
    service = AlertService(conn)
    return await service.create_alert(alert)


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    user_id: Annotated[str, Query(description="User ID to fetch alerts for")],
    status_filter: Annotated[AlertStatus | None, Query(alias="status")] = None,
    alert_type: Annotated[AlertType | None, Query()] = None,
    priority: Annotated[AlertPriority | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)] = None,
) -> AlertListResponse:
    """
    List alerts for a user with optional filters.
    
    - **user_id**: User identifier
    - **status**: Filter by alert status (UNREAD, READ, DISMISSED, ARCHIVED)
    - **alert_type**: Filter by alert type
    - **priority**: Filter by priority level
    - **page**: Page number (starts at 1)
    - **page_size**: Items per page (max 100)
    """
    service = AlertService(conn)
    offset = (page - 1) * page_size
    
    alerts, total = await service.list_alerts(
        user_id=user_id,
        status=status_filter,
        alert_type=alert_type,
        priority=priority,
        limit=page_size,
        offset=offset,
    )
    
    unread_count = await service.get_unread_count(user_id)
    
    return AlertListResponse(
        alerts=alerts,
        total=total,
        page=page,
        page_size=page_size,
        unread_count=unread_count,
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: UUID,
    user_id: Annotated[str, Query(description="User ID for authorization")],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertResponse:
    """
    Get a specific alert by ID.
    
    - **alert_id**: Alert UUID
    - **user_id**: User ID for authorization
    """
    service = AlertService(conn)
    alert = await service.get_alert(alert_id, user_id)
    
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found or access denied",
        )
    
    return alert


@router.patch("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: UUID,
    user_id: Annotated[str, Query(description="User ID for authorization")],
    update: AlertUpdate,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertResponse:
    """
    Update an alert (typically to mark as read/dismissed).
    
    - **alert_id**: Alert UUID
    - **user_id**: User ID for authorization
    - **status**: New status (READ, DISMISSED, ARCHIVED)
    """
    service = AlertService(conn)
    
    if update.status:
        alert = await service.update_alert_status(alert_id, user_id, update.status)
    else:
        alert = await service.get_alert(alert_id, user_id)
    
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found or access denied",
        )
    
    return alert


@router.post("/mark-all-read")
async def mark_all_as_read(
    user_id: Annotated[str, Query(description="User ID")],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> dict[str, int]:
    """
    Mark all unread alerts as read for a user.
    
    - **user_id**: User identifier
    
    Returns the count of alerts marked as read.
    """
    service = AlertService(conn)
    count = await service.mark_all_as_read(user_id)
    
    return {"marked_read": count}


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: UUID,
    user_id: Annotated[str, Query(description="User ID for authorization")],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> None:
    """
    Delete an alert.
    
    - **alert_id**: Alert UUID
    - **user_id**: User ID for authorization
    """
    service = AlertService(conn)
    deleted = await service.delete_alert(alert_id, user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found or access denied",
        )


@router.get("/stats/summary", response_model=AlertStatsResponse)
async def get_alert_stats(
    user_id: Annotated[str, Query(description="User ID")],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AlertStatsResponse:
    """
    Get alert statistics for a user.
    
    - **user_id**: User identifier
    
    Returns counts by priority, type, and recent alerts.
    """
    service = AlertService(conn)
    
    # Get all alerts for stats
    all_alerts, total = await service.list_alerts(user_id, limit=1000, offset=0)
    unread_count = await service.get_unread_count(user_id)
    
    # Calculate stats
    by_priority: dict[str, int] = {}
    by_type: dict[str, int] = {}
    
    for alert in all_alerts:
        by_priority[alert.priority.value] = by_priority.get(alert.priority.value, 0) + 1
        by_type[alert.alert_type.value] = by_type.get(alert.alert_type.value, 0) + 1
    
    # Get recent alerts (last 5)
    recent_alerts = all_alerts[:5]
    
    return AlertStatsResponse(
        total_alerts=total,
        unread_count=unread_count,
        by_priority=by_priority,
        by_type=by_type,
        recent_alerts=recent_alerts,
    )


@router.post("/archive-expired")
async def archive_expired_alerts(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> dict[str, int]:
    """
    Archive all expired alerts (admin endpoint).
    
    Returns the count of alerts archived.
    """
    service = AlertService(conn)
    count = await service.archive_expired_alerts()
    
    return {"archived": count}
