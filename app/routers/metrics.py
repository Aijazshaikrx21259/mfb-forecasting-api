"""System metrics and performance endpoints."""

from typing import Annotated
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
import asyncpg

from app.db import get_db_connection
from app.security import verify_api_key
from pydantic import BaseModel


class SystemMetrics(BaseModel):
    """System performance metrics."""
    
    total_requests: int
    avg_response_time_ms: float
    error_rate_pct: float
    active_users: int
    forecast_runs_today: int
    alerts_generated_today: int
    adjustments_pending: int
    timestamp: datetime


class CostEstimate(BaseModel):
    """Cloud cost estimation."""
    
    database_queries_today: int
    estimated_db_cost_usd: float
    api_requests_today: int
    estimated_api_cost_usd: float
    total_estimated_cost_usd: float
    period_start: datetime
    period_end: datetime


router = APIRouter(
    prefix="/api/metrics",
    tags=["metrics"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/system", response_model=SystemMetrics)
async def get_system_metrics(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> SystemMetrics:
    """
    Get current system performance metrics.
    
    Returns operational metrics for monitoring dashboard.
    """
    # Mock data for now - would be collected from actual metrics store
    return SystemMetrics(
        total_requests=12500,
        avg_response_time_ms=245.5,
        error_rate_pct=0.5,
        active_users=15,
        forecast_runs_today=3,
        alerts_generated_today=42,
        adjustments_pending=8,
        timestamp=datetime.utcnow(),
    )


@router.get("/costs", response_model=CostEstimate)
async def get_cost_estimate(
    days: Annotated[int, Query(ge=1, le=30)] = 1,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)] = None,
) -> CostEstimate:
    """
    Get estimated cloud costs for the specified period.
    
    - **days**: Number of days to estimate (1-30)
    """
    # Mock cost estimation - would be calculated from actual usage
    db_queries = 50000 * days
    api_requests = 10000 * days
    
    # Rough estimates (adjust based on actual pricing)
    db_cost = (db_queries / 1000000) * 0.25  # $0.25 per million queries
    api_cost = (api_requests / 1000000) * 0.10  # $0.10 per million requests
    
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)
    
    return CostEstimate(
        database_queries_today=db_queries,
        estimated_db_cost_usd=round(db_cost, 2),
        api_requests_today=api_requests,
        estimated_api_cost_usd=round(api_cost, 2),
        total_estimated_cost_usd=round(db_cost + api_cost, 2),
        period_start=period_start,
        period_end=period_end,
    )
