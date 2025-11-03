-- Populate sample backtest data for development/demo purposes
-- This adds backtest metrics for the items that have forecast data

-- First, ensure the tables exist (from local_backtest_stub.sql)
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS core;

-- Use the same run_id as the forecast data
DO $$
DECLARE
    sample_run_id uuid := 'b5d44473-f5a5-415c-8f6e-869ad13f7f8d';
BEGIN
    -- Clear any existing sample data for this run
    DELETE FROM analytics.backtest_item_summary WHERE run_id = sample_run_id;
    DELETE FROM analytics.backtest_overall_summary WHERE run_id = sample_run_id;

    -- Insert sample backtest metrics for each item
    -- MAPE values are realistic (10-40%), beats_benchmark is varied
    INSERT INTO analytics.backtest_item_summary 
        (run_id, item_id, model_name, horizon_months, n_windows, n_windows_mape_den, mape, rmse, beats_benchmark, created_at)
    VALUES
        (sample_run_id, 'P-352101', 'TSB', 1, 12, 12, 23.45, 145.2, true, now()),
        (sample_run_id, 'P-352718', 'TSB', 1, 12, 12, 28.76, 178.5, true, now()),
        (sample_run_id, 'P-906104', 'TSB', 1, 12, 12, 19.82, 132.8, true, now()),
        (sample_run_id, 'P-911018', 'TSB', 1, 12, 12, 31.24, 156.3, false, now()),
        (sample_run_id, 'P-915001', 'TSB', 1, 12, 12, 26.18, 142.7, true, now()),
        (sample_run_id, 'P-915032', 'TSB', 1, 12, 12, 22.91, 138.4, true, now()),
        (sample_run_id, 'P-915120', 'TSB', 1, 12, 12, 17.65, 128.9, true, now()),
        (sample_run_id, 'P-915133', 'TSB', 1, 12, 12, 29.43, 165.2, false, now()),
        (sample_run_id, 'P-923005', 'TSB', 1, 12, 12, 24.77, 149.6, true, now()),
        (sample_run_id, 'P-926004', 'TSB', 1, 12, 12, 33.82, 182.1, false, now()),
        (sample_run_id, 'P-943036', 'TSB', 1, 12, 12, 21.34, 135.5, true, now()),
        (sample_run_id, 'P-949205', 'TSB', 1, 12, 12, 27.58, 158.9, true, now()),
        (sample_run_id, 'P-949218', 'TSB', 1, 12, 12, 25.12, 147.3, true, now()),
        (sample_run_id, 'P-950114', 'TSB', 1, 12, 12, 30.45, 171.2, false, now()),
        (sample_run_id, 'P-950126', 'TSB', 1, 12, 12, 18.93, 126.4, true, now());

    -- Insert overall summary
    INSERT INTO analytics.backtest_overall_summary
        (run_id, horizon_months, items_evaluated, pct_items_mape_lt_30, pct_items_beating_sn, mean_mape, mean_rmse, created_at)
    VALUES
        (sample_run_id, 1, 15, 66.67, 73.33, 25.47, 150.53, now());

    RAISE NOTICE 'Sample backtest data populated successfully for run_id: %', sample_run_id;
END $$;

