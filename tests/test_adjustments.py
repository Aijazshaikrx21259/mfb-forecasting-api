"""Tests for forecast adjustment system."""

import pytest
from datetime import date, datetime
from uuid import uuid4
from unittest.mock import AsyncMock

from app.models.adjustments import (
    AdjustmentCreate,
    AdjustmentUpdate,
    AdjustmentReview,
    AdjustmentStatus,
)
from app.services.adjustment_service import AdjustmentService


@pytest.fixture
def mock_adjustment_row():
    """Create a mock adjustment database row."""
    adjustment_id = uuid4()
    run_id = uuid4()
    return {
        "adjustment_id": adjustment_id,
        "item_id": "P-352101",
        "run_id": run_id,
        "horizon": 1,
        "period_start_date": date(2024, 1, 1),
        "original_p50": 100.0,
        "original_p10": 80.0,
        "original_p90": 120.0,
        "original_method": "TSB",
        "adjusted_p50": 150.0,
        "adjusted_p10": 130.0,
        "adjusted_p90": 170.0,
        "adjustment_reason": "Promotional event expected",
        "notes": "Holiday season promotion",
        "confidence_level": 4,
        "adjusted_by": "user123",
        "adjusted_at": datetime.utcnow(),
        "status": "PENDING",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_adjustment(mock_db_connection, mock_adjustment_row):
    """Test creating a forecast adjustment."""
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_adjustment_row)
    
    service = AdjustmentService(mock_db_connection)
    adjustment_create = AdjustmentCreate(
        item_id="P-352101",
        run_id=mock_adjustment_row["run_id"],
        horizon=1,
        period_start_date=date(2024, 1, 1),
        original_p50=100.0,
        adjusted_p50=150.0,
        adjustment_reason="Promotional event expected",
        adjusted_by="user123",
    )
    
    result = await service.create_adjustment(adjustment_create)
    
    assert result.item_id == "P-352101"
    assert result.adjusted_p50 == 150.0
    assert result.status == AdjustmentStatus.PENDING
    assert mock_db_connection.fetchrow.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_adjustment(mock_db_connection, mock_adjustment_row):
    """Test retrieving a specific adjustment."""
    adjustment_id = mock_adjustment_row["adjustment_id"]
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_adjustment_row)
    
    service = AdjustmentService(mock_db_connection)
    result = await service.get_adjustment(adjustment_id)
    
    assert result is not None
    assert result.adjustment_id == adjustment_id
    assert result.item_id == "P-352101"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_adjustments(mock_db_connection, mock_adjustment_row):
    """Test listing adjustments with filters."""
    mock_db_connection.fetchval = AsyncMock(return_value=5)
    mock_db_connection.fetch = AsyncMock(return_value=[mock_adjustment_row])
    
    service = AdjustmentService(mock_db_connection)
    adjustments, total = await service.list_adjustments(
        item_id="P-352101",
        limit=10,
        offset=0,
    )
    
    assert len(adjustments) == 1
    assert total == 5
    assert adjustments[0].item_id == "P-352101"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_adjustment(mock_db_connection, mock_adjustment_row):
    """Test updating an adjustment."""
    mock_adjustment_row["adjusted_p50"] = 175.0
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_adjustment_row)
    
    service = AdjustmentService(mock_db_connection)
    update = AdjustmentUpdate(adjusted_p50=175.0)
    
    result = await service.update_adjustment(
        adjustment_id=mock_adjustment_row["adjustment_id"],
        update=update,
    )
    
    assert result is not None
    assert result.adjusted_p50 == 175.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_review_adjustment_approve(mock_db_connection, mock_adjustment_row):
    """Test approving an adjustment."""
    mock_adjustment_row["status"] = "APPROVED"
    mock_adjustment_row["reviewed_by"] = "reviewer123"
    mock_adjustment_row["reviewed_at"] = datetime.utcnow()
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_adjustment_row)
    
    service = AdjustmentService(mock_db_connection)
    review = AdjustmentReview(
        status=AdjustmentStatus.APPROVED,
        reviewed_by="reviewer123",
        review_notes="Looks good",
    )
    
    result = await service.review_adjustment(
        adjustment_id=mock_adjustment_row["adjustment_id"],
        review=review,
    )
    
    assert result is not None
    assert result.status == AdjustmentStatus.APPROVED
    assert result.reviewed_by == "reviewer123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_review_adjustment_reject(mock_db_connection, mock_adjustment_row):
    """Test rejecting an adjustment."""
    mock_adjustment_row["status"] = "REJECTED"
    mock_adjustment_row["reviewed_by"] = "reviewer123"
    mock_adjustment_row["review_notes"] = "Insufficient justification"
    mock_db_connection.fetchrow = AsyncMock(return_value=mock_adjustment_row)
    
    service = AdjustmentService(mock_db_connection)
    review = AdjustmentReview(
        status=AdjustmentStatus.REJECTED,
        reviewed_by="reviewer123",
        review_notes="Insufficient justification",
    )
    
    result = await service.review_adjustment(
        adjustment_id=mock_adjustment_row["adjustment_id"],
        review=review,
    )
    
    assert result is not None
    assert result.status == AdjustmentStatus.REJECTED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_adjustment(mock_db_connection):
    """Test deleting an adjustment."""
    mock_db_connection.execute = AsyncMock(return_value="DELETE 1")
    
    service = AdjustmentService(mock_db_connection)
    result = await service.delete_adjustment(uuid4())
    
    assert result is True


@pytest.mark.unit
def test_adjustment_create_validation():
    """Test AdjustmentCreate model validation."""
    # Valid adjustment
    adjustment = AdjustmentCreate(
        item_id="P-352101",
        run_id=uuid4(),
        horizon=1,
        period_start_date=date(2024, 1, 1),
        adjusted_p50=150.0,
        adjustment_reason="Valid reason with enough characters",
        adjusted_by="user123",
    )
    assert adjustment.adjusted_p50 == 150.0
    
    # Test negative value validation
    with pytest.raises(ValueError):
        AdjustmentCreate(
            item_id="P-352101",
            run_id=uuid4(),
            horizon=1,
            period_start_date=date(2024, 1, 1),
            adjusted_p50=-10.0,  # Negative not allowed
            adjustment_reason="Valid reason",
            adjusted_by="user123",
        )


@pytest.mark.unit
def test_adjustment_bounds_validation():
    """Test that p10 <= p50 <= p90 validation works."""
    # Valid bounds
    adjustment = AdjustmentCreate(
        item_id="P-352101",
        run_id=uuid4(),
        horizon=1,
        period_start_date=date(2024, 1, 1),
        adjusted_p50=150.0,
        adjusted_p10=130.0,
        adjusted_p90=170.0,
        adjustment_reason="Valid reason with enough characters",
        adjusted_by="user123",
    )
    assert adjustment.adjusted_p10 < adjustment.adjusted_p50 < adjustment.adjusted_p90
    
    # Invalid: p10 > p50
    with pytest.raises(ValueError):
        AdjustmentCreate(
            item_id="P-352101",
            run_id=uuid4(),
            horizon=1,
            period_start_date=date(2024, 1, 1),
            adjusted_p50=150.0,
            adjusted_p10=160.0,  # p10 > p50
            adjusted_p90=170.0,
            adjustment_reason="Valid reason",
            adjusted_by="user123",
        )


@pytest.mark.unit
def test_adjustment_status_enum():
    """Test AdjustmentStatus enum values."""
    assert AdjustmentStatus.PENDING.value == "PENDING"
    assert AdjustmentStatus.APPROVED.value == "APPROVED"
    assert AdjustmentStatus.REJECTED.value == "REJECTED"
    assert AdjustmentStatus.SUPERSEDED.value == "SUPERSEDED"
    assert len(AdjustmentStatus) == 4


@pytest.mark.unit
def test_adjustment_review_validation():
    """Test that review status must be APPROVED or REJECTED."""
    # Valid review
    review = AdjustmentReview(
        status=AdjustmentStatus.APPROVED,
        reviewed_by="reviewer123",
    )
    assert review.status == AdjustmentStatus.APPROVED
    
    # Invalid: cannot review with PENDING status
    with pytest.raises(ValueError):
        AdjustmentReview(
            status=AdjustmentStatus.PENDING,
            reviewed_by="reviewer123",
        )
