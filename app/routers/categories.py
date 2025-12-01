"""Category-level demand insights endpoints for US #15."""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.db import get_db_connection
from app.security import verify_api_key


class CategoryDemandResponse(BaseModel):
    """Category demand aggregation."""
    category: str
    total_demand: float
    item_count: int
    avg_demand_per_item: float


class CategoryForecastResponse(BaseModel):
    """Category forecast aggregation."""
    category: str
    total_forecast: float
    item_count: int
    avg_forecast_per_item: float
    horizon_months: int


class CategoryListResponse(BaseModel):
    """List of available categories."""
    categories: list[str]
    total_categories: int


router = APIRouter(
    prefix="/api/categories",
    tags=["categories"],
    dependencies=[Depends(verify_api_key)],
)


def _extract_category_from_item_id(item_id: str) -> str:
    """
    Extract category from item ID.
    Simplified logic: use first character/prefix as category.
    In production, this would query a proper category dimension table.
    """
    if not item_id:
        return "UNKNOWN"
    
    # Simple categorization based on item ID prefix
    prefix = item_id[0].upper()
    
    category_map = {
        "P": "Produce",
        "D": "Dairy",
        "M": "Meat",
        "B": "Bakery",
        "C": "Canned Goods",
        "F": "Frozen",
        "G": "Grains",
        "S": "Snacks",
    }
    
    return category_map.get(prefix, "Other")


@router.get("/", response_model=CategoryListResponse)
async def list_categories(
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> CategoryListResponse:
    """
    Return list of available categories.
    
    This endpoint supports US #15: Category-Level Demand Insights.
    """
    
    # For now, return predefined categories
    # In production, this would query the category dimension table
    categories = [
        "Produce",
        "Dairy",
        "Meat",
        "Bakery",
        "Canned Goods",
        "Frozen",
        "Grains",
        "Snacks",
        "Other",
    ]
    
    return CategoryListResponse(
        categories=categories,
        total_categories=len(categories),
    )


@router.get("/demand", response_model=list[CategoryDemandResponse])
async def get_category_demand(
    horizon: int = Query(default=1, ge=1, description="Forecast horizon in months."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[CategoryDemandResponse]:
    """
    Return aggregated demand by category.
    
    This endpoint supports US #15: Category-Level Demand Insights.
    """
    
    try:
        # Get forecast data and categorize by item ID prefix
        records = await connection.fetch(
            """
            SELECT 
                item_id,
                p50
            FROM analytics.forecast_item_month
            WHERE horizon_months = $1
              AND p50 IS NOT NULL
            ORDER BY item_id
            """,
            horizon,
        )
        
        if not records:
            return []
        
        # Aggregate by category
        category_data: dict[str, dict] = {}
        
        for record in records:
            item_id = record["item_id"]
            demand = float(record["p50"]) if record["p50"] is not None else 0.0
            category = _extract_category_from_item_id(item_id)
            
            if category not in category_data:
                category_data[category] = {
                    "total_demand": 0.0,
                    "item_count": 0,
                }
            
            category_data[category]["total_demand"] += demand
            category_data[category]["item_count"] += 1
        
        # Build response
        result = []
        for category, data in sorted(category_data.items()):
            avg_demand = data["total_demand"] / data["item_count"] if data["item_count"] > 0 else 0.0
            result.append(
                CategoryDemandResponse(
                    category=category,
                    total_demand=data["total_demand"],
                    item_count=data["item_count"],
                    avg_demand_per_item=avg_demand,
                )
            )
        
        return result
        
    except asyncpg.exceptions.UndefinedTableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forecast tables are not available in the database.",
        ) from exc


@router.get("/forecast", response_model=list[CategoryForecastResponse])
async def get_category_forecast(
    horizon: int = Query(default=1, ge=1, description="Forecast horizon in months."),
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[CategoryForecastResponse]:
    """
    Return aggregated forecasts by category.
    
    This endpoint supports US #15: Category-Level Demand Insights.
    """
    
    try:
        # Get forecast data with categories from dim_item
        records = await connection.fetch(
            """
            SELECT 
                COALESCE(di.category, 'Other') as category,
                SUM(f.p50) as total_forecast,
                COUNT(DISTINCT f.item_id) as item_count
            FROM analytics.forecast_item_month f
            LEFT JOIN core.dim_item di ON f.item_id = di.item_id
            WHERE f.horizon_months = $1
              AND f.p50 IS NOT NULL
            GROUP BY di.category
            ORDER BY total_forecast DESC
            """,
            horizon,
        )
        
        if not records:
            return []
        
        # Build response
        result = []
        for record in records:
            category = record["category"] or "Other"
            total_forecast = float(record["total_forecast"]) if record["total_forecast"] else 0.0
            item_count = record["item_count"]
            avg_forecast = total_forecast / item_count if item_count > 0 else 0.0
            
            result.append(
                CategoryForecastResponse(
                    category=category,
                    total_forecast=total_forecast,
                    item_count=item_count,
                    avg_forecast_per_item=avg_forecast,
                    horizon_months=horizon,
                )
            )
        
        return result
        
    except asyncpg.exceptions.UndefinedTableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forecast tables are not available in the database.",
        ) from exc
