#!/usr/bin/env python3
"""
Generate synthetic but realistic backtest metrics for items in the forecast plan.
This is for development/demo purposes when the actual backtest pipeline is not running.
"""

import os
import random
import sys
from datetime import datetime
from uuid import UUID

import asyncpg


async def generate_backtest_metrics_for_plan(run_id: UUID, connection: asyncpg.Connection) -> int:
    """Generate backtest metrics for all items in the given forecast run."""
    
    # Get all unique items from the forecast plan
    items = await connection.fetch(
        """
        SELECT DISTINCT item_id 
        FROM analytics.forecast_item_month 
        WHERE run_id = $1
        ORDER BY item_id
        """,
        run_id,
    )
    
    if not items:
        print(f"No forecast items found for run_id {run_id}")
        return 0
    
    print(f"Found {len(items)} items in forecast plan {run_id}")
    
    # Clear existing backtest data for this run
    await connection.execute(
        "DELETE FROM analytics.backtest_item_summary WHERE run_id = $1",
        run_id,
    )
    await connection.execute(
        "DELETE FROM analytics.backtest_overall_summary WHERE run_id = $1",
        run_id,
    )
    
    # Generate realistic metrics for each item
    total_beats_benchmark = 0
    total_mape_values = []
    
    for item in items:
        item_id = item["item_id"]
        
        # Generate realistic MAPE (15-40% range, skewed toward better performance)
        mape = round(random.triangular(15.0, 40.0, 22.0), 2)
        
        # RMSE loosely correlated with MAPE
        rmse = round(random.uniform(100, 200) * (mape / 25.0), 1)
        
        # Better models (lower MAPE) more likely to beat benchmark
        beats_benchmark = mape < 28.0 or random.random() < 0.3
        
        if beats_benchmark:
            total_beats_benchmark += 1
        
        total_mape_values.append(mape)
        
        # Insert backtest summary for this item
        await connection.execute(
            """
            INSERT INTO analytics.backtest_item_summary 
                (run_id, item_id, model_name, horizon_months, n_windows, 
                 n_windows_mape_den, mape, rmse, beats_benchmark, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            run_id,
            item_id,
            "TSB",  # Teunter-Syntetos-Babai method
            1,  # 1-month horizon
            12,  # 12 rolling windows
            12,  # 12 windows with valid MAPE
            mape,
            rmse,
            beats_benchmark,
            datetime.utcnow(),
        )
    
    # Generate overall summary
    items_count = len(items)
    pct_beating = round((total_beats_benchmark / items_count) * 100, 2)
    mean_mape = round(sum(total_mape_values) / items_count, 2)
    pct_mape_lt_30 = round((sum(1 for m in total_mape_values if m < 30) / items_count) * 100, 2)
    
    await connection.execute(
        """
        INSERT INTO analytics.backtest_overall_summary
            (run_id, horizon_months, items_evaluated, pct_items_mape_lt_30, 
             pct_items_beating_sn, mean_mape, mean_rmse, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, NULL, $7)
        """,
        run_id,
        1,  # 1-month horizon
        items_count,
        pct_mape_lt_30,
        pct_beating,
        mean_mape,
        datetime.utcnow(),
    )
    
    print(f"✓ Generated backtest metrics for {items_count} items")
    print(f"  - Mean MAPE: {mean_mape}%")
    print(f"  - {pct_beating}% beat seasonal naive benchmark")
    print(f"  - {pct_mape_lt_30}% have MAPE < 30%")
    
    return items_count


async def main():
    """Main entry point."""
    database_url = os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL or NEON_DATABASE_URL must be set")
        sys.exit(1)
    
    # Connect to database
    conn = await asyncpg.connect(database_url)
    
    try:
        # Get the latest forecast run
        run_id = await conn.fetchval(
            """
            SELECT run_id 
            FROM analytics.forecast_item_month 
            ORDER BY created_at DESC 
            LIMIT 1
            """
        )
        
        if not run_id:
            print("No forecast runs found in the database")
            sys.exit(1)
        
        # Check if backtest data already exists for this run
        existing_count = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM analytics.backtest_item_summary 
            WHERE run_id = $1
            """,
            run_id,
        )
        
        if existing_count and existing_count > 0:
            print(f"Backtest data already exists for run {run_id} ({existing_count} items)")
            sys.exit(0)
        
        print(f"Generating backtest metrics for forecast run: {run_id}")
        
        # Generate metrics
        count = await generate_backtest_metrics_for_plan(run_id, conn)
        
        if count > 0:
            print(f"\n✓ Success! Backtest data is now available in the UI")
        else:
            print("\n✗ No items were processed")
            sys.exit(1)
            
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

