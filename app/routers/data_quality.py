"""Data quality management endpoints."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.db import get_db_connection
from app.security import verify_api_key

# Simple in-memory cache for data quality summary
_CACHE: dict[str, tuple[datetime, Any]] = {}
_CACHE_TTL = timedelta(minutes=5)  # Cache for 5 minutes


class FlagType(str, Enum):
    ANOMALY = "ANOMALY"
    STOCKOUT = "STOCKOUT"
    BAD_DATA = "BAD_DATA"
    MANUAL_EXCLUDE = "MANUAL_EXCLUDE"


class MonthFlagCreate(BaseModel):
    month_key: str
    agency_internal_id: str | None = None
    item_id: str | None = None
    flag_type: FlagType
    flag_reason: str | None = None
    expires_at_utc: datetime | None = None

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("month_key")
    @classmethod
    def validate_month_key(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            msg = "month_key must follow YYYY-MM format"
            raise ValueError(msg)
        return value


class MonthFlagResponse(BaseModel):
    flag_id: UUID
    month_key: str
    agency_internal_id: str | None
    item_id: str | None
    flag_type: FlagType
    flag_level: str
    flag_reason: str | None
    flagged_by: str
    flagged_at_utc: datetime
    expires_at_utc: datetime | None
    is_active: bool
    detected_issue_id: UUID | None


class DeactivateRequest(BaseModel):
    flag_id: UUID


class CandidateResponse(BaseModel):
    candidate_id: UUID
    month_key: str
    agency_internal_id: str | None
    item_id: str | None
    flag_type: FlagType
    flag_level: str
    flag_reason: str | None
    detected_rule: str | None
    detected_score: float | None
    detected_at_utc: datetime


class DataTreatmentSummary(BaseModel):
    """Before/after data treatment metrics."""
    total_item_months: int
    flagged_item_months: int
    clean_item_months: int
    exclusion_rate: float  # percentage
    items_affected: int


class ActionableInsight(BaseModel):
    """Actionable insight with priority and recommendation."""
    priority: str  # HIGH, MEDIUM, LOW
    issue_type: str
    count: int
    title: str
    description: str
    impact: str
    recommended_action: str


class QualitySummaryResponse(BaseModel):
    """Comprehensive data quality summary for US #21."""
    total_flags: int
    active_flags: int
    flags_by_type: dict[str, int]
    flags_by_level: dict[str, int]
    anomaly_candidates: int
    recent_issues: list[MonthFlagResponse]
    data_completeness_score: float  # 0-100
    quality_score: float  # 0-100
    data_treatment: DataTreatmentSummary
    actionable_insights: list[ActionableInsight]


router = APIRouter(
    prefix="/api/data-quality",
    tags=["data-quality"],
    dependencies=[Depends(verify_api_key)],
)


def _determine_flag_level(agency_internal_id: str | None, item_id: str | None) -> str:
    if agency_internal_id and item_id:
        return "AGENCY_ITEM"
    if agency_internal_id:
        return "AGENCY"
    if item_id:
        return "ITEM"
    return "GLOBAL"


def _generate_actionable_insights(
    flags_by_type: dict[str, int],
    active_flags: int,
    items_affected: int,
    exclusion_rate: float,
) -> list[ActionableInsight]:
    """Generate prioritized actionable insights based on data quality issues."""
    insights: list[ActionableInsight] = []
    
    # Define issue type metadata
    issue_metadata = {
        "ANOMALY": {
            "title": "Volume Anomalies Detected",
            "description": "Demand patterns show unusual spikes or drops (>70% deviation from baseline)",
            "impact": f"May cause forecast inaccuracy if anomalies represent one-time events rather than trend changes",
            "action": "Review flagged items to determine if anomalies are data errors, one-time events, or genuine demand shifts",
            "priority_threshold": 100,
        },
        "BAD_DATA": {
            "title": "Data Quality Issues Found",
            "description": "Source system changes, negative values, or inconsistent data detected",
            "impact": f"Unreliable data will produce unreliable forecasts and may exclude items from predictions",
            "action": "Investigate data source issues and correct upstream data collection problems",
            "priority_threshold": 50,
        },
        "STOCKOUT": {
            "title": "Potential Stockouts Identified",
            "description": "Items with sustained demand suddenly dropped to zero quantity",
            "impact": f"Stockouts can be misinterpreted as demand decline, leading to under-forecasting",
            "action": "Verify if zero-demand periods are true stockouts and flag them to prevent forecast bias",
            "priority_threshold": 20,
        },
        "MANUAL_EXCLUDE": {
            "title": "Manual Exclusions Active",
            "description": "Items or periods manually excluded from forecasting",
            "impact": f"Reduces available training data and may affect forecast coverage",
            "action": "Review manual exclusions periodically to ensure they're still necessary",
            "priority_threshold": 30,
        },
    }
    
    # Generate insights for each issue type
    for issue_type, count in sorted(flags_by_type.items(), key=lambda x: x[1], reverse=True):
        if count == 0:
            continue
            
        metadata = issue_metadata.get(issue_type, {
            "title": f"{issue_type} Issues",
            "description": f"{count} issues of type {issue_type} detected",
            "impact": "May affect forecast quality",
            "action": "Review and resolve these issues",
            "priority_threshold": 50,
        })
        
        # Determine priority
        if count >= metadata["priority_threshold"]:
            priority = "HIGH"
        elif count >= metadata["priority_threshold"] // 2:
            priority = "MEDIUM"
        else:
            priority = "LOW"
        
        insights.append(ActionableInsight(
            priority=priority,
            issue_type=issue_type,
            count=count,
            title=metadata["title"],
            description=metadata["description"],
            impact=metadata["impact"],
            recommended_action=metadata["action"],
        ))
    
    # Add overall health insight if no issues
    if active_flags == 0:
        insights.append(ActionableInsight(
            priority="LOW",
            issue_type="HEALTHY",
            count=0,
            title="Data Quality: Excellent",
            description="All data quality checks are passing",
            impact="Your data is clean and ready for accurate forecasting",
            recommended_action="Continue monitoring data quality with each new data load",
        ))
    elif exclusion_rate > 20:
        # Add high exclusion rate warning
        insights.insert(0, ActionableInsight(
            priority="HIGH",
            issue_type="HIGH_EXCLUSION",
            count=int(exclusion_rate),
            title=f"High Data Exclusion Rate ({exclusion_rate:.1f}%)",
            description=f"{items_affected} items affected by quality flags, excluding significant training data",
            impact="Reduced training data may lead to less accurate forecasts and limited item coverage",
            recommended_action="Prioritize resolving data quality issues to maximize available training data",
        ))
    
    return insights


async def _fetch_flag_record(record: asyncpg.Record | None) -> MonthFlagResponse:
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")
    payload: dict[str, Any] = dict(record)
    return MonthFlagResponse(**payload)


@router.post("/flags", response_model=MonthFlagResponse, status_code=status.HTTP_201_CREATED)
async def create_month_flag(
    request: MonthFlagCreate,
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> MonthFlagResponse:
    """Create or update a manual month quality flag."""

    flag_level = _determine_flag_level(request.agency_internal_id, request.item_id)

    appended_reason = request.flag_reason.strip() if request.flag_reason else "Manual exclusion"
    system_row = await connection.fetchrow(
        """
        SELECT flag_id, flag_reason
        FROM analytics.month_quality_flag
        WHERE month_key = $1
          AND COALESCE(agency_internal_id, '') = COALESCE($2, '')
          AND COALESCE(item_id, '') = COALESCE($3, '')
          AND flagged_by = 'SYSTEM'
          AND is_active = TRUE
        ORDER BY flagged_at_utc DESC
        LIMIT 1
        """,
        request.month_key,
        request.agency_internal_id,
        request.item_id,
    )

    if system_row and system_row.get("flag_reason"):
        appended_reason = f"{appended_reason} | system: {system_row['flag_reason']}"

    if system_row:
        await connection.execute(
            "UPDATE analytics.month_quality_flag SET is_active = FALSE WHERE flag_id = $1",
            system_row["flag_id"],
        )

    record = await connection.fetchrow(
        """
        INSERT INTO analytics.month_quality_flag (
            month_key,
            agency_internal_id,
            item_id,
            flag_type,
            flag_level,
            flag_reason,
            flagged_by,
            flagged_at_utc,
            expires_at_utc,
            is_active
        )
        VALUES ($1, $2, $3, $4, $5, $6, 'USER', now(), $7, TRUE)
        ON CONFLICT (scope_key) DO UPDATE
        SET
            flag_type = EXCLUDED.flag_type,
            flag_level = EXCLUDED.flag_level,
            flag_reason = EXCLUDED.flag_reason,
            flagged_at_utc = now(),
            expires_at_utc = EXCLUDED.expires_at_utc,
            is_active = TRUE,
            flagged_by = 'USER'
        RETURNING *
        """,
        request.month_key,
        request.agency_internal_id,
        request.item_id,
        request.flag_type.value,
        flag_level,
        appended_reason,
        request.expires_at_utc,
    )

    return await _fetch_flag_record(record)


@router.get("/flags", response_model=list[MonthFlagResponse])
async def list_month_flags(
    month_key: str | None = Query(default=None, description="Filter by month key (YYYY-MM)."),
    agency_internal_id: str | None = Query(default=None, description="Filter by agency identifier."),
    item_id: str | None = Query(default=None, description="Filter by item identifier."),
    include_inactive: bool = Query(default=False, description="Include inactive flags."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[MonthFlagResponse]:
    """Return matching quality flags."""

    records = await connection.fetch(
        """
        SELECT *
        FROM analytics.month_quality_flag
        WHERE ($1::text IS NULL OR month_key = $1)
          AND ($2::text IS NULL OR agency_internal_id = $2)
          AND ($3::text IS NULL OR item_id = $3)
          AND ($4::boolean OR is_active = TRUE)
        ORDER BY month_key DESC, flagged_at_utc DESC
        """,
        month_key,
        agency_internal_id,
        item_id,
        include_inactive,
    )

    return [MonthFlagResponse(**dict(record)) for record in records]


@router.post("/flags/deactivate", response_model=MonthFlagResponse)
async def deactivate_flag(
    request: DeactivateRequest,
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> MonthFlagResponse:
    """Deactivate a specific flag by identifier."""

    record = await connection.fetchrow(
        """
        UPDATE analytics.month_quality_flag
        SET is_active = FALSE, flagged_at_utc = now()
        WHERE flag_id = $1
        RETURNING *
        """,
        request.flag_id,
    )

    return await _fetch_flag_record(record)


@router.get("/candidates", response_model=list[CandidateResponse])
async def list_anomaly_candidates(
    month_key: str | None = Query(default=None, description="Filter anomaly candidates by month key."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[CandidateResponse]:
    """Expose system-generated anomaly candidates for review."""

    records = await connection.fetch(
        """
        SELECT *
        FROM analytics.system_anomaly_candidates
        WHERE ($1::text IS NULL OR month_key = $1)
        ORDER BY detected_at_utc DESC
        """,
        month_key,
    )

    result: list[CandidateResponse] = []
    for record in records:
        payload: dict[str, Any] = dict(record)
        if payload.get("detected_score") is not None:
            payload["detected_score"] = float(payload["detected_score"])
        result.append(CandidateResponse(**payload))
    return result


@router.get("/summary", response_model=QualitySummaryResponse)
async def get_quality_summary(
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> QualitySummaryResponse:
    """
    Return comprehensive data quality summary with metrics and recent issues.
    
    This endpoint supports US #21: Data Quality Monitoring Report.
    """
    
    # Check cache first
    cache_key = "quality_summary"
    now = datetime.utcnow()
    if cache_key in _CACHE:
        cached_time, cached_data = _CACHE[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_data
    
    try:
        # Get total and active flags count
        flag_counts = await connection.fetchrow(
            """
            SELECT 
                COUNT(*) as total_flags,
                COUNT(*) FILTER (WHERE is_active = TRUE) as active_flags
            FROM analytics.month_quality_flag
            """
        )
        
        total_flags = flag_counts["total_flags"] if flag_counts else 0
        active_flags = flag_counts["active_flags"] if flag_counts else 0
        
        # Get flags by type
        type_records = await connection.fetch(
            """
            SELECT flag_type, COUNT(*) as count
            FROM analytics.month_quality_flag
            WHERE is_active = TRUE
            GROUP BY flag_type
            """
        )
        
        flags_by_type = {record["flag_type"]: record["count"] for record in type_records}
        
        # Get flags by level
        level_records = await connection.fetch(
            """
            SELECT flag_level, COUNT(*) as count
            FROM analytics.month_quality_flag
            WHERE is_active = TRUE
            GROUP BY flag_level
            """
        )
        
        flags_by_level = {record["flag_level"]: record["count"] for record in level_records}
        
        # Get anomaly candidates count
        candidates_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM analytics.system_anomaly_candidates
            """
        )
        
        anomaly_candidates = candidates_count or 0
        
        # Get recent issues (last 10 active flags)
        recent_records = await connection.fetch(
            """
            SELECT *
            FROM analytics.month_quality_flag
            WHERE is_active = TRUE
            ORDER BY flagged_at_utc DESC
            LIMIT 10
            """
        )
        
        recent_issues = [MonthFlagResponse(**dict(record)) for record in recent_records]
        
        # Get data treatment metrics (before/after) - OPTIMIZED
        treatment_metrics = await connection.fetchrow(
            """
            WITH flagged_data AS (
                SELECT DISTINCT 
                    month_key,
                    item_id
                FROM analytics.month_quality_flag
                WHERE is_active = TRUE
            ),
            actuals_summary AS (
                SELECT 
                    COUNT(DISTINCT item_id || '-' || month_key) as total_item_months,
                    COUNT(DISTINCT item_id) as total_items
                FROM analytics.item_agency_monthly_actuals
            ),
            flagged_summary AS (
                SELECT COUNT(DISTINCT 
                    CASE 
                        WHEN f.item_id IS NOT NULL THEN a.item_id || '-' || a.month_key
                        ELSE a.item_id || '-' || a.month_key
                    END
                ) as flagged_item_months
                FROM analytics.item_agency_monthly_actuals a
                LEFT JOIN flagged_data f ON (
                    a.month_key = f.month_key 
                    AND (a.item_id = f.item_id OR f.item_id IS NULL)
                )
                WHERE f.month_key IS NOT NULL
            )
            SELECT 
                a.total_item_months,
                COALESCE(f.flagged_item_months, 0) as flagged_item_months,
                a.total_items
            FROM actuals_summary a
            CROSS JOIN flagged_summary f
            """
        )
        
        total_item_months = treatment_metrics["total_item_months"] if treatment_metrics else 0
        flagged_item_months = treatment_metrics["flagged_item_months"] if treatment_metrics else 0
        clean_item_months = max(0, total_item_months - flagged_item_months)
        exclusion_rate = (flagged_item_months / total_item_months * 100) if total_item_months > 0 else 0.0
        
        # Count unique items affected by flags
        items_affected_count = await connection.fetchval(
            """
            SELECT COUNT(DISTINCT item_id)
            FROM analytics.month_quality_flag
            WHERE is_active = TRUE AND item_id IS NOT NULL
            """
        ) or 0
        
        # Calculate data completeness score
        data_completeness_score = max(0.0, min(100.0, (clean_item_months / total_item_months * 100) if total_item_months > 0 else 100.0))
        
        # Calculate overall quality score (fixed: 100% when no issues)
        if active_flags == 0:
            quality_score = 100.0
        else:
            # Deduct based on exclusion rate and issue severity
            quality_score = max(0.0, 100.0 - exclusion_rate - (active_flags * 0.01))
        
        # Generate actionable insights
        insights = _generate_actionable_insights(flags_by_type, active_flags, items_affected_count, exclusion_rate)
        
    except asyncpg.exceptions.UndefinedTableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Data quality tables are not available in the database.",
        ) from exc
    
    response = QualitySummaryResponse(
        total_flags=int(total_flags),
        active_flags=int(active_flags),
        flags_by_type=flags_by_type,
        flags_by_level=flags_by_level,
        anomaly_candidates=int(anomaly_candidates),
        recent_issues=recent_issues,
        data_completeness_score=data_completeness_score,
        quality_score=quality_score,
        data_treatment=DataTreatmentSummary(
            total_item_months=int(total_item_months),
            flagged_item_months=int(flagged_item_months),
            clean_item_months=int(clean_item_months),
            exclusion_rate=round(exclusion_rate, 2),
            items_affected=int(items_affected_count),
        ),
        actionable_insights=insights,
    )
    
    # Cache the response
    _CACHE[cache_key] = (now, response)
    
    return response


