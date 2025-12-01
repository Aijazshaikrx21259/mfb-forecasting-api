"""Automatic alert generation based on forecast data."""

import json
from typing import List
import asyncpg


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
    
    # Get top 10 items by forecast quantity
    top_items = await connection.fetch("""
        SELECT 
            item_id,
            p50 as forecast_qty,
            period_start_date
        FROM analytics.forecast_item_month
        WHERE run_id = $1
        AND horizon_months = 1
        AND p50 IS NOT NULL
        ORDER BY p50 DESC
        LIMIT 10
    """, run_id)
    
    if not top_items:
        return 0
    
    total_qty = sum(item['forecast_qty'] for item in top_items)
    item_list = ', '.join([item['item_id'] for item in top_items[:5]])
    
    # Get high-demand items (potential stockout risk)
    high_demand_items = [item for item in top_items if item['forecast_qty'] > 1000]
    
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
