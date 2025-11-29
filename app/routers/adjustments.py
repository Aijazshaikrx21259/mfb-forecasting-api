"""Forecast adjustment endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
import asyncpg

from app.db import get_db_connection
from app.security import verify_api_key
from app.models.adjustments import (
    AdjustmentCreate,
    AdjustmentResponse,
    AdjustmentUpdate,
    AdjustmentReview,
    AdjustmentListResponse,
    AdjustmentStatus,
    AdjustmentHistoryEntry,
    AdjustmentTemplate,
    AdjustmentStatsResponse,
)
from app.services.adjustment_service import AdjustmentService


router = APIRouter(
    prefix="/api/adjustments",
    tags=["adjustments"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("", response_model=AdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    adjustment: AdjustmentCreate,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AdjustmentResponse:
    """
    Create a new forecast adjustment.
    
    Allows users to manually override forecasted quantities with justification.
    
    - **item_id**: Item identifier
    - **run_id**: Forecast run UUID
    - **horizon**: Forecast horizon (1-12 months)
    - **period_start_date**: Period being adjusted
    - **adjusted_p50**: New median forecast value
    - **adjustment_reason**: Required justification (min 10 chars)
    - **notes**: Optional additional context
    - **confidence_level**: 1=Low to 5=High confidence
    """
    service = AdjustmentService(conn)
    return await service.create_adjustment(adjustment)


@router.get("", response_model=AdjustmentListResponse)
async def list_adjustments(
    item_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[AdjustmentStatus | None, Query(alias="status")] = None,
    adjusted_by: Annotated[str | None, Query()] = None,
    period_start_date: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)] = None,
) -> AdjustmentListResponse:
    """
    List forecast adjustments with optional filters.
    
    - **item_id**: Filter by item
    - **run_id**: Filter by forecast run
    - **status**: Filter by status (PENDING, APPROVED, REJECTED, SUPERSEDED)
    - **adjusted_by**: Filter by user
    - **period_start_date**: Filter by period
    - **page**: Page number (starts at 1)
    - **page_size**: Items per page (max 100)
    """
    service = AdjustmentService(conn)
    offset = (page - 1) * page_size
    
    adjustments, total = await service.list_adjustments(
        item_id=item_id,
        run_id=run_id,
        status=status_filter,
        adjusted_by=adjusted_by,
        period_start_date=period_start_date,
        limit=page_size,
        offset=offset,
    )
    
    return AdjustmentListResponse(
        adjustments=adjustments,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{adjustment_id}", response_model=AdjustmentResponse)
async def get_adjustment(
    adjustment_id: UUID,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AdjustmentResponse:
    """
    Get a specific adjustment by ID.
    
    - **adjustment_id**: Adjustment UUID
    """
    service = AdjustmentService(conn)
    adjustment = await service.get_adjustment(adjustment_id)
    
    if not adjustment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    return adjustment


@router.patch("/{adjustment_id}", response_model=AdjustmentResponse)
async def update_adjustment(
    adjustment_id: UUID,
    update: AdjustmentUpdate,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AdjustmentResponse:
    """
    Update an existing adjustment.
    
    Only pending adjustments can be updated.
    
    - **adjustment_id**: Adjustment UUID
    - **adjusted_p50**: New median forecast value
    - **adjustment_reason**: Updated justification
    - **notes**: Updated notes
    """
    service = AdjustmentService(conn)
    
    # Check if adjustment exists and is pending
    existing = await service.get_adjustment(adjustment_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    if existing.status != AdjustmentStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot update adjustment with status {existing.status.value}",
        )
    
    result = await service.update_adjustment(adjustment_id, update)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    return result


@router.post("/{adjustment_id}/review", response_model=AdjustmentResponse)
async def review_adjustment(
    adjustment_id: UUID,
    review: AdjustmentReview,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AdjustmentResponse:
    """
    Review an adjustment (approve or reject).
    
    - **adjustment_id**: Adjustment UUID
    - **status**: APPROVED or REJECTED
    - **review_notes**: Optional review comments
    - **reviewed_by**: Reviewer user ID
    """
    service = AdjustmentService(conn)
    
    # Check if adjustment exists
    existing = await service.get_adjustment(adjustment_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    if existing.status != AdjustmentStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Adjustment already reviewed with status {existing.status.value}",
        )
    
    result = await service.review_adjustment(adjustment_id, review)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    return result


@router.delete("/{adjustment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_adjustment(
    adjustment_id: UUID,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> None:
    """
    Delete an adjustment.
    
    Only pending or rejected adjustments can be deleted.
    
    - **adjustment_id**: Adjustment UUID
    """
    service = AdjustmentService(conn)
    
    # Check if adjustment exists and can be deleted
    existing = await service.get_adjustment(adjustment_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    if existing.status in (AdjustmentStatus.APPROVED, AdjustmentStatus.SUPERSEDED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete adjustment with status {existing.status.value}",
        )
    
    deleted = await service.delete_adjustment(adjustment_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )


@router.get("/{adjustment_id}/history", response_model=list[AdjustmentHistoryEntry])
async def get_adjustment_history(
    adjustment_id: UUID,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> list[AdjustmentHistoryEntry]:
    """
    Get change history for an adjustment.
    
    Returns audit trail of all changes made to the adjustment.
    
    - **adjustment_id**: Adjustment UUID
    """
    service = AdjustmentService(conn)
    
    # Verify adjustment exists
    adjustment = await service.get_adjustment(adjustment_id)
    if not adjustment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjustment {adjustment_id} not found",
        )
    
    return await service.get_adjustment_history(adjustment_id)


@router.get("/active/{item_id}", response_model=AdjustmentResponse | None)
async def get_active_adjustment(
    item_id: str,
    period_start_date: Annotated[date, Query()],
    run_id: Annotated[UUID | None, Query()] = None,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)] = None,
) -> AdjustmentResponse | None:
    """
    Get the active (approved) adjustment for an item/period.
    
    Returns the most recent approved adjustment if one exists.
    
    - **item_id**: Item identifier
    - **period_start_date**: Period date
    - **run_id**: Optional forecast run filter
    """
    service = AdjustmentService(conn)
    return await service.get_active_adjustment(item_id, period_start_date, run_id)


@router.get("/templates/list", response_model=list[AdjustmentTemplate])
async def list_templates(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> list[AdjustmentTemplate]:
    """
    List all available adjustment templates.
    
    Templates provide pre-configured adjustment scenarios (e.g., +10%, -20%, set to zero).
    """
    service = AdjustmentService(conn)
    return await service.list_templates()


@router.post("/templates/{template_id}/apply", response_model=AdjustmentResponse)
async def apply_template(
    template_id: str,
    item_id: Annotated[str, Query()],
    run_id: Annotated[UUID, Query()],
    horizon: Annotated[int, Query(ge=1, le=12)],
    period_start_date: Annotated[date, Query()],
    original_p50: Annotated[float, Query(ge=0)],
    adjusted_by: Annotated[str, Query()],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)] = None,
) -> AdjustmentResponse:
    """
    Apply an adjustment template to create a new adjustment.
    
    - **template_id**: Template identifier (e.g., 'increase_10pct')
    - **item_id**: Item to adjust
    - **run_id**: Forecast run
    - **horizon**: Forecast horizon
    - **period_start_date**: Period date
    - **original_p50**: Original forecast value
    - **adjusted_by**: User ID
    """
    service = AdjustmentService(conn)
    
    try:
        return await service.apply_template(
            template_id=template_id,
            item_id=item_id,
            run_id=run_id,
            horizon=horizon,
            period_start_date=period_start_date,
            original_p50=original_p50,
            adjusted_by=adjusted_by,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/stats/summary", response_model=AdjustmentStatsResponse)
async def get_adjustment_stats(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> AdjustmentStatsResponse:
    """
    Get adjustment statistics.
    
    Returns counts by status, user, and item with recent adjustments.
    """
    service = AdjustmentService(conn)
    
    # Get all adjustments for stats
    all_adjustments, total = await service.list_adjustments(limit=1000, offset=0)
    
    # Calculate stats
    pending_count = sum(1 for a in all_adjustments if a.status == AdjustmentStatus.PENDING)
    approved_count = sum(1 for a in all_adjustments if a.status == AdjustmentStatus.APPROVED)
    rejected_count = sum(1 for a in all_adjustments if a.status == AdjustmentStatus.REJECTED)
    
    by_user: dict[str, int] = {}
    by_item: dict[str, int] = {}
    adjustment_pcts = []
    
    for adj in all_adjustments:
        by_user[adj.adjusted_by] = by_user.get(adj.adjusted_by, 0) + 1
        by_item[adj.item_id] = by_item.get(adj.item_id, 0) + 1
        
        if adj.original_p50 and adj.original_p50 > 0:
            pct_change = ((adj.adjusted_p50 - adj.original_p50) / adj.original_p50) * 100
            adjustment_pcts.append(pct_change)
    
    avg_adjustment_pct = sum(adjustment_pcts) / len(adjustment_pcts) if adjustment_pcts else None
    
    # Get recent adjustments (last 10)
    recent_adjustments = all_adjustments[:10]
    
    return AdjustmentStatsResponse(
        total_adjustments=total,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        by_user=by_user,
        by_item=by_item,
        avg_adjustment_pct=avg_adjustment_pct,
        recent_adjustments=recent_adjustments,
    )
