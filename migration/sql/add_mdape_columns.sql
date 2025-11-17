-- Add MdAPE support columns/tables required by the auto-forecast optimizations.
-- Run this against existing Neon/Postgres environments before redeploying the API.

ALTER TABLE IF EXISTS analytics.backtest_metrics
    ADD COLUMN IF NOT EXISTS mdape double precision;

ALTER TABLE IF EXISTS analytics.item_champion
    ADD COLUMN IF NOT EXISTS mdape double precision;

CREATE TABLE IF NOT EXISTS analytics.backtest_residual_summary (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    horizon int NOT NULL,
    method text NOT NULL,
    abs_p90 double precision,
    abs_p95 double precision,
    mdape double precision,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id, horizon, method)
);

ALTER TABLE IF EXISTS analytics.backtest_residual_summary
    ADD COLUMN IF NOT EXISTS mdape double precision;

CREATE TABLE IF NOT EXISTS analytics.forecast_alert (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    horizon int NOT NULL,
    method text NOT NULL,
    metric text NOT NULL,
    value double precision,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id, horizon, method, metric)
);
