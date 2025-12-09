"""Automatic alert generation based on forecast data."""

import json
from typing import List
import asyncpg
from datetime import datetime, timedelta


async def generate_purchase_alerts(
    connection: asyncpg.Connection,
    run_id: str,
    user_ids: List[str] = None
) -> int:
    """
    Generate weekly purchase alerts for top items based on latest forecast.
    
    Args:
        connection: Database connection
        run_id: Forecast run ID
        user_ids: List of user IDs to notify (if None, notifies all active users)
    
    Returns:
        Number of alerts created
    """
    
    # Get items that need purchasing (forecast > 0, indicating demand)
    purchase_items = await connection.fetch("""
        SELECT 
            item_id,
            p50 as forecast_qty,
            period_start_date
        FROM analytics.forecast_item_month
        WHERE run_id = $1
        AND horizon_months = 1
        AND p50 > 0
        ORDER BY p50 DESC
    """, run_id)
    
    if not purchase_items:
        return 0
    
    # Get top 10 for the digest
    top_items = purchase_items[:10]
    total_qty = sum(item['forecast_qty'] for item in top_items)
    item_list = ', '.join([item['item_id'] for item in top_items[:5]])
    
    # All items with forecast > 0 are potential stockout risks if not ordered
    high_demand_items = purchase_items
    
    # If no user_ids provided, get all active users or use a default
    if not user_ids:
        # For now, use a default "all-users" approach
        # In production, this would query active users from a users table
        user_ids = ["all-users"]
    
    alerts_created = 0
    
    for user_id in user_ids:
        # Create weekly digest alert
        try:
            await connection.fetchval("""
                SELECT alerts.create_alert_from_template(
                    $1::TEXT,
                    'weekly_digest'::TEXT,
                    $2::JSONB,
                    '/purchase-plan'::TEXT,
                    168
                )
            """, user_id, json.dumps({
                'items_count': str(len(top_items)),
                'total_qty': f"{total_qty:,.0f}",
                'top_items': item_list,
                'run_id': str(run_id)
            }))
            alerts_created += 1
        except Exception:
            pass  # Skip if alert already exists
        
        # Create stockout risk alert if applicable
        if high_demand_items:
            try:
                await connection.fetchval("""
                    SELECT alerts.create_alert_from_template(
                        $1::TEXT,
                        'stockout_risk'::TEXT,
                        $2::JSONB,
                        '/purchase-plan'::TEXT,
                        72
                    )
                """, user_id, json.dumps({
                    'items_count': str(len(high_demand_items)),
                    'items': ', '.join([item['item_id'] for item in high_demand_items[:3]]),
                    'run_id': str(run_id)
                }))
                alerts_created += 1
            except Exception:
                pass
    
    return alerts_created


async def generate_forecast_ready_alert(
    connection: asyncpg.Connection,
    run_id: str,
    items_count: int,
    horizons: List[int],
    user_ids: List[str] = None
) -> int:
    """Generate alert when new forecast is ready."""
    
    if not user_ids:
        user_ids = ["all-users"]
    
    alerts_created = 0
    
    for user_id in user_ids:
        try:
            await connection.fetchval("""
                SELECT alerts.create_alert_from_template(
                    $1::TEXT,
                    'forecast_ready'::TEXT,
                    $2::JSONB,
                    '/items'::TEXT,
                    168
                )
            """, user_id, json.dumps({
                'run_id': str(run_id),
                'items_count': str(items_count),
                'horizons': ', '.join(map(str, horizons))
            }))
            alerts_created += 1
        except Exception:
            pass
    
    return alerts_created


async def generate_deviation_alerts(
    connection: asyncpg.Connection,
    run_id: str,
    user_ids: List[str] = None,
    deviation_threshold: float = 30.0
) -> int:
    """
    Generate alerts for items where forecast deviates significantly from historical average.
    
    This supports US #17: Smart Alert System for demand deviations.
    
    Args:
        connection: Database connection
        run_id: Forecast run ID
        user_ids: List of user IDs to notify
        deviation_threshold: Percentage deviation threshold (default 30%)
    
    Returns:
        Number of alerts created
    """
    
    if not user_ids:
        user_ids = ["all-users"]
    
    # Find items where forecast deviates significantly from historical average
    deviating_items = await connection.fetch("""
        WITH historical_avg AS (
            SELECT 
                item_id,
                AVG(demand) as avg_demand
            FROM analytics.item_month_demand
            WHERE demand > 0
            GROUP BY item_id
        ),
        forecast_data AS (
            SELECT 
                item_id,
                p50 as forecast
            FROM analytics.forecast_item_month
            WHERE run_id = $1
            AND horizon_months = 1
            AND p50 IS NOT NULL
        )
        SELECT 
            f.item_id,
            f.forecast,
            h.avg_demand,
            CASE 
                WHEN h.avg_demand > 0 THEN 
                    ABS((f.forecast - h.avg_demand) / h.avg_demand * 100)
                ELSE 0
            END as deviation_pct,
            CASE
                WHEN f.forecast > h.avg_demand THEN 'INCREASE'
                ELSE 'DECREASE'
            END as direction
        FROM forecast_data f
        INNER JOIN historical_avg h ON f.item_id = h.item_id
        WHERE h.avg_demand > 0
        AND ABS((f.forecast - h.avg_demand) / h.avg_demand * 100) > $2
        ORDER BY deviation_pct DESC
        LIMIT 10
    """, run_id, deviation_threshold)
    
    if not deviating_items:
        return 0
    
    alerts_created = 0
    
    # Calculate summary stats
    increases = [item for item in deviating_items if item['direction'] == 'INCREASE']
    decreases = [item for item in deviating_items if item['direction'] == 'DECREASE']
    
    for user_id in user_ids:
        # Alert for significant increases
        if increases:
            try:
                await connection.fetchval("""
                    SELECT alerts.create_alert_from_template(
                        $1::TEXT,
                        'high_demand_spike'::TEXT,
                        $2::JSONB,
                        '/items'::TEXT,
                        72
                    )
                """, user_id, json.dumps({
                    'items_count': str(len(increases)),
                    'threshold': f"{deviation_threshold:.0f}",
                    'top_items': ', '.join([item['item_id'] for item in increases[:3]])
                }))
                alerts_created += 1
            except Exception:
                pass
        
        # Alert for significant decreases
        if decreases:
            try:
                await connection.fetchval("""
                    SELECT alerts.create_alert_from_template(
                        $1::TEXT,
                        'low_demand_drop'::TEXT,
                        $2::JSONB,
                        '/items'::TEXT,
                        72
                    )
                """, user_id, json.dumps({
                    'items_count': str(len(decreases)),
                    'threshold': f"{deviation_threshold:.0f}",
                    'top_items': ', '.join([item['item_id'] for item in decreases[:3]])
                }))
                alerts_created += 1
            except Exception:
                pass
    
    return alerts_created
