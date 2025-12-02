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
    
    database_size_mb: float
    total_items: int
    total_forecasts: int
    last_pipeline_run: datetime | None
    avg_api_response_ms: float


class CostEstimate(BaseModel):
    """Cloud cost estimation."""
    
    daily_cost_usd: float
    monthly_estimate_usd: float
    database_storage_cost: float
    compute_cost: float


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
    Get current system performance metrics from Neon database.
    
    Returns operational metrics for monitoring dashboard.
    """
    # Get database size in MB
    db_size_bytes = await conn.fetchval(
        "SELECT pg_database_size(current_database())"
    )
    db_size_mb = db_size_bytes / (1024 * 1024) if db_size_bytes else 0
    
    # Get total items
    total_items = await conn.fetchval(
        "SELECT COUNT(*) FROM core.dim_item"
    ) or 0
    
    # Get total forecasts
    total_forecasts = await conn.fetchval(
        "SELECT COUNT(*) FROM analytics.forecast_item_month"
    ) or 0
    
    # Get last pipeline run
    last_run = await conn.fetchval(
        "SELECT MAX(created_at) FROM analytics.forecast_run"
    )
    
    return SystemMetrics(
        database_size_mb=db_size_mb,
        total_items=total_items,
        total_forecasts=total_forecasts,
        last_pipeline_run=last_run,
        avg_api_response_ms=125.0,  # Would be from metrics collection
    )


@router.get("/costs", response_model=CostEstimate)
async def get_cost_estimate(
    days: Annotated[int, Query(ge=1, le=30)] = 1,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)] = None,
) -> CostEstimate:
    """
    Get estimated Neon cloud costs based on database size.
    
    - **days**: Number of days to estimate (1-30)
    """
    # Get database size for cost calculation
    db_size_bytes = await conn.fetchval(
        "SELECT pg_database_size(current_database())"
    ) if conn else 0
    db_size_gb = (db_size_bytes / (1024 ** 3)) if db_size_bytes else 0
    
    # Neon pricing estimates (adjust based on actual plan)
    # Free tier: 0.5 GB, Paid: ~$0.10/GB/month for storage
    storage_cost_per_day = (db_size_gb * 0.10) / 30 if db_size_gb > 0.5 else 0
    compute_cost_per_day = 0.50  # Estimated compute cost per day
    
    daily_cost = storage_cost_per_day + compute_cost_per_day
    monthly_estimate = daily_cost * 30
    
    return CostEstimate(
        daily_cost_usd=round(daily_cost, 2),
        monthly_estimate_usd=round(monthly_estimate, 2),
        database_storage_cost=round(storage_cost_per_day, 2),
        compute_cost=round(compute_cost_per_day, 2),
    )
