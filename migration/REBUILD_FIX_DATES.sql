-- ================================================================
-- STEP 1: Clear Old Data with Wrong Dates
-- ================================================================

-- Clear analytics demand table (will be rebuilt with correct dates)
TRUNCATE TABLE analytics.item_month_demand CASCADE;

-- Clear dimension tables (will be rebuilt with correct dates)
TRUNCATE TABLE core.dim_month CASCADE;
TRUNCATE TABLE core.dim_calendar_month CASCADE;

-- Clear all forecast data (will be regenerated with correct dates)
TRUNCATE TABLE analytics.forecast_item_month CASCADE;
TRUNCATE TABLE analytics.item_champion CASCADE;
TRUNCATE TABLE analytics.backtest_window_error CASCADE;
TRUNCATE TABLE analytics.forecast_run CASCADE;

-- Confirm cleanup
SELECT 'Old data cleared successfully!' as status;

-- ================================================================
-- STEP 2: Rebuild Dimension Tables with Fixed SQL
-- ================================================================

-- Now run these SQL files in order:
-- 1. migration/sql/core_dim_month.sql (ALREADY UPDATED - now uses 4 months)
-- 2. migration/sql/core_dim_item.sql
-- 3. migration/sql/analytics_item_month_demand.sql (ALREADY UPDATED - now uses 4 months)

-- ================================================================
-- STEP 3: Verify the Fix
-- ================================================================

-- Check the new date range (run this AFTER rebuilding)
-- Should show max_month is NOW + 4 months (not NOW + 12 months)
SELECT 
    MIN(month_start)::text as first_month,
    MAX(month_start)::text as last_month,
    (MAX(month_start) - CURRENT_DATE) as days_from_today,
    CASE 
        WHEN (MAX(month_start) - CURRENT_DATE) <= 150 THEN '✅ CORRECT (within 5 months)'
        ELSE '❌ STILL WRONG (more than 5 months ahead)'
    END as status
FROM analytics.item_month_demand;

-- Check item P-352101 specifically
SELECT 
    month_start,
    demand,
    is_synthetic,
    CASE 
        WHEN month_start > CURRENT_DATE + INTERVAL '5 months' THEN '❌ Too far in future'
        ELSE '✅ OK'
    END as check_status
FROM analytics.item_month_demand
WHERE item_id = 'P-352101'
ORDER BY month_start DESC
LIMIT 10;

