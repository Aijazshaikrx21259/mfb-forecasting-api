"""Pydantic models for forecast adjustments."""

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AdjustmentStatus(str, Enum):
    """Adjustment status enumeration."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AdjustmentCreate(BaseModel):
    """Request model for creating a forecast adjustment."""

    item_id: str = Field(..., description="Item identifier")
    run_id: UUID = Field(..., description="Forecast run UUID")
    horizon: int = Field(..., ge=1, le=12, description="Forecast horizon (1-12 months)")
    period_start_date: date = Field(..., description="Period start date")
    
    # Original values (for reference)
    original_p50: float | None = None
    original_p10: float | None = None
    original_p90: float | None = None
    original_method: str | None = None
    
    # Adjusted values
    adjusted_p50: float = Field(..., ge=0, description="Adjusted median forecast")
    adjusted_p10: float | None = Field(None, ge=0, description="Adjusted lower bound (p10)")
    adjusted_p90: float | None = Field(None, ge=0, description="Adjusted upper bound (p90)")
    
    # Metadata
    adjustment_reason: str = Field(..., min_length=10, max_length=500, description="Reason for adjustment")
    notes: str | None = Field(None, max_length=2000, description="Additional notes")
    confidence_level: int | None = Field(None, ge=1, le=5, description="Confidence level (1=Low, 5=High)")
    
    adjusted_by: str = Field(..., description="User ID or email")

    @field_validator("adjusted_p10", "adjusted_p90")
    @classmethod
    def validate_bounds(cls, v: float | None, info) -> float | None:
        """Validate confidence bounds."""
        if v is not None and v < 0:
            raise ValueError("Confidence bounds must be non-negative")
        return v

    def model_post_init(self, __context: Any) -> None:
        """Validate that p10 <= p50 <= p90."""
        if self.adjusted_p10 is not None and self.adjusted_p10 > self.adjusted_p50:
            raise ValueError("adjusted_p10 must be <= adjusted_p50")
        if self.adjusted_p90 is not None and self.adjusted_p90 < self.adjusted_p50:
            raise ValueError("adjusted_p90 must be >= adjusted_p50")


class AdjustmentResponse(BaseModel):
    """Response model for adjustment data."""

    adjustment_id: UUID
    item_id: str
    run_id: UUID
    horizon: int
    period_start_date: date
    
    original_p50: float | None
    original_p10: float | None
    original_p90: float | None
    original_method: str | None
    
    adjusted_p50: float
    adjusted_p10: float | None
    adjusted_p90: float | None
    
    adjustment_reason: str
    notes: str | None
    confidence_level: int | None
    
    adjusted_by: str
    adjusted_at: datetime
    
    status: AdjustmentStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdjustmentUpdate(BaseModel):
    """Request model for updating an adjustment."""

    adjusted_p50: float | None = Field(None, ge=0)
    adjusted_p10: float | None = Field(None, ge=0)
    adjusted_p90: float | None = Field(None, ge=0)
    adjustment_reason: str | None = Field(None, min_length=10, max_length=500)
    notes: str | None = Field(None, max_length=2000)
    confidence_level: int | None = Field(None, ge=1, le=5)


class AdjustmentReview(BaseModel):
    """Request model for reviewing an adjustment."""

    status: AdjustmentStatus = Field(..., description="APPROVED or REJECTED")
    review_notes: str | None = Field(None, max_length=1000)
    reviewed_by: str = Field(..., description="Reviewer user ID or email")

    @field_validator("status")
    @classmethod
    def validate_review_status(cls, v: AdjustmentStatus) -> AdjustmentStatus:
        """Ensure status is either APPROVED or REJECTED."""
        if v not in (AdjustmentStatus.APPROVED, AdjustmentStatus.REJECTED):
            raise ValueError("Review status must be APPROVED or REJECTED")
        return v


class AdjustmentListResponse(BaseModel):
    """Response model for paginated adjustment list."""

    adjustments: list[AdjustmentResponse]
    total: int
    page: int
    page_size: int


class AdjustmentHistoryEntry(BaseModel):
    """Response model for adjustment history entry."""

    history_id: UUID
    adjustment_id: UUID
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by: str
    changed_at: datetime
    change_reason: str | None

    class Config:
        from_attributes = True


class AdjustmentTemplate(BaseModel):
    """Response model for adjustment template."""

    template_id: str
    template_name: str
    description: str | None
    adjustment_type: str
    adjustment_value: float | None
    adjustment_formula: str | None
    default_reason: str | None
    default_confidence: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdjustmentStatsResponse(BaseModel):
    """Response model for adjustment statistics."""

    total_adjustments: int
    pending_count: int
    approved_count: int
    rejected_count: int
    by_user: dict[str, int]
    by_item: dict[str, int]
    avg_adjustment_pct: float | None
    recent_adjustments: list[AdjustmentResponse]
