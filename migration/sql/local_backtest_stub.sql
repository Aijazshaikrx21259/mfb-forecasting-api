-- Dev-only backtest scaffolding so /api/backtest/run enqueues real rows when the
-- production pipeline objects are unavailable. Run this against your local Neon
-- database to create minimal queue + result tables and the core.enqueue_backtest_run
-- function expected by the FastAPI endpoint.

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;

-- Queue header for overall runs.
CREATE TABLE IF NOT EXISTS core.backtest_run_queue (
    run_id uuid PRIMARY KEY,
    horizons int[] NOT NULL,
    step_size int NOT NULL,
    n_windows int,
    status text NOT NULL DEFAULT 'PENDING',
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);

-- Queue of per-item jobs (simple illustration; adapt for real pipeline usage).
CREATE TABLE IF NOT EXISTS core.backtest_job_queue (
    job_id bigserial PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES core.backtest_run_queue(run_id),
    item_id text NOT NULL,
    horizon int NOT NULL,
    status text NOT NULL DEFAULT 'PENDING',
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);

-- Minimal result tables so the FastAPI endpoints have data to read. Replace with
-- the full production schema when available.
CREATE TABLE IF NOT EXISTS core.backtest_window_errors (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    origin_month date NOT NULL,
    horizon_months int NOT NULL,
    model_name text NOT NULL,
    y_true numeric,
    y_pred numeric,
    err numeric,
    abs_pct_err numeric,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics.backtest_item_summary (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    model_name text NOT NULL,
    horizon_months int NOT NULL,
    n_windows int NOT NULL,
    n_windows_mape_den int,
    mape numeric,
    rmse numeric,
    beats_benchmark boolean,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics.backtest_overall_summary (
    run_id uuid NOT NULL,
    horizon_months int NOT NULL,
    items_evaluated int NOT NULL,
    pct_items_mape_lt_30 numeric,
    pct_items_beating_sn numeric,
    mean_mape numeric,
    mean_rmse numeric,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, horizon_months)
);

-- Create the enqueue function so the FastAPI endpoint can add rows to the queue.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE OR REPLACE FUNCTION core.enqueue_backtest_run(
    horizons int[],
    step_size int,
    n_windows int
)
RETURNS TABLE(run_id uuid, items_enqueued int, windows_enqueued int)
LANGUAGE plpgsql
AS $$
DECLARE
    new_run_id uuid := uuid_generate_v4();
    item record;
    horizon int;
    total_jobs int := 0;
BEGIN
    IF horizons IS NULL OR array_length(horizons, 1) = 0 THEN
        RAISE EXCEPTION 'At least one horizon is required';
    END IF;

    INSERT INTO core.backtest_run_queue (run_id, horizons, step_size, n_windows)
    VALUES (new_run_id, horizons, step_size, n_windows);

    -- TODO: replace this stub list with a real query against analytics.item_month_demand
    -- or another item catalogue. We include a few placeholder IDs for demonstration.
    FOR item IN SELECT UNNEST(ARRAY['ITEM-1', 'ITEM-2', 'ITEM-3']) AS item_id
    LOOP
        FOREACH horizon IN ARRAY horizons
        LOOP
            INSERT INTO core.backtest_job_queue (run_id, item_id, horizon)
            VALUES (new_run_id, item.item_id, horizon);
            total_jobs := total_jobs + 1;
        END LOOP;
    END LOOP;

    RETURN QUERY
    SELECT new_run_id, total_jobs, total_jobs * COALESCE(n_windows, 0);
END;
$$;

COMMENT ON FUNCTION core.enqueue_backtest_run(int[], int, int) IS
    'Dev-only stub: enqueues placeholder backtest jobs so the FastAPI API can return real queue data.';

