#!/bin/bash
set -e

echo "=========================================="
echo "Rebuilding Analytics with Fixed Dates"
echo "=========================================="
echo ""
echo "This script will:"
echo "1. Clear existing analytics data"
echo "2. Rebuild with calendar extending only 4 months (not 12)"
echo "3. Regenerate forecasts with correct dates"
echo ""

cd "$(dirname "$0")/.."

# Load environment
if [ -f "migration/.env" ]; then
    export $(grep -v '^#' migration/.env | xargs)
fi

if [ -z "$NEON_DATABASE_URL" ]; then
    echo "❌ Error: NEON_DATABASE_URL not set"
    echo "Please set it in migration/.env or export it"
    exit 1
fi

echo "📊 Step 1: Resetting analytics data..."
python migration/load_excel_to_neon.py reset-data \
    --truncate-demand \
    --truncate-dims \
    --no-truncate-staging \
    --no-truncate-core

echo ""
echo "🔧 Step 2: Rebuilding analytics with fixed calendar..."
python migration/load_excel_to_neon.py build-analytics

echo ""
echo "📈 Step 3: Checking calendar range..."
psql "$NEON_DATABASE_URL" <<SQL
SELECT 
    MIN(month_start)::text as first_month,
    MAX(month_start)::text as last_month,
    (MAX(month_start) - CURRENT_DATE) as days_from_today,
    COUNT(DISTINCT item_id) as item_count,
    COUNT(*) as total_rows
FROM analytics.item_month_demand;
SQL

echo ""
echo "🔍 Step 4: Clearing old forecasts..."
psql "$NEON_DATABASE_URL" <<SQL
TRUNCATE TABLE analytics.forecast_item_month CASCADE;
TRUNCATE TABLE analytics.item_champion CASCADE;
TRUNCATE TABLE analytics.backtest_window_error CASCADE;
TRUNCATE TABLE analytics.forecast_run CASCADE;
SQL

echo ""
echo "✅ Analytics rebuild complete!"
echo ""
echo "Next steps:"
echo "1. Start the API: docker compose up -d"
echo "2. Trigger new forecast: Visit an item page in the UI"
echo "3. Or run manually: docker compose exec api python -c 'from app.services.pipeline_scheduler import run_forecast_pipeline; import asyncio; asyncio.run(run_forecast_pipeline())'"
echo ""
echo "Then visit: http://localhost:3000/items/P-352101"
echo ""

