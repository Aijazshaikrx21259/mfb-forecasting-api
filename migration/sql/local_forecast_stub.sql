-- Dev-only scaffolding for the forecasting pipeline introduced in user story 5.
-- Run this against your local Neon (or Postgres) database when you need the
-- FastAPI endpoints to persist champion selections and forecast outputs without
-- the full production warehouse models.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.item_classification (
    item_id text PRIMARY KEY,
    demand_class text NOT NULL,
    adi double precision,
    cv2 double precision,
    obsolescence_flag boolean DEFAULT FALSE,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics.backtest_metrics (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    horizon int NOT NULL,
    method text NOT NULL,
    mape double precision,
    rmse double precision,
    mdape double precision,
    beats_baseline boolean,
    fold_count int,
    mape_denominator_count int,
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id, horizon, method)
);

CREATE TABLE IF NOT EXISTS analytics.item_champion (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    horizon int NOT NULL,
    champion_method text NOT NULL,
    mape double precision,
    rmse double precision,
    mdape double precision,
    beats_baseline boolean,
    needs_review boolean DEFAULT FALSE,
    demand_class text,
    obsolescence_flag boolean,
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id, horizon)
);

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

CREATE TABLE IF NOT EXISTS analytics.forecast_item_month (
    run_id uuid NOT NULL,
    item_id text NOT NULL,
    period_start_date date NOT NULL,
    horizon_months int NOT NULL,
    method text NOT NULL,
    p50 double precision,
    p10 double precision,
    p90 double precision,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id, horizon_months, period_start_date)
);

CREATE INDEX IF NOT EXISTS ix_forecast_item_month_item_h ON analytics.forecast_item_month (item_id, horizon_months);

CREATE TABLE IF NOT EXISTS analytics.forecast_run (
    run_id uuid PRIMARY KEY,
    horizons int[] NOT NULL,
    status text NOT NULL,
    items_evaluated int,
    items_with_champion int,
    items_beating_baseline int,
    items_forecasted int,
    champion_counts jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    forecast_generated_at timestamptz
);

COMMENT ON TABLE analytics.item_classification IS
    'Stores ADI/CV^2 demand class derived from core.item_month_demand and the obsolescence flag used to gate TSB.';

COMMENT ON TABLE analytics.backtest_metrics IS
    'Rolling-origin cross-validation metrics (MAPE/RMSE/MdAPE) per item/horizon/method.';

COMMENT ON TABLE analytics.item_champion IS
    'Champion method per item & horizon with guardrail flags and MdAPE.';

COMMENT ON TABLE analytics.backtest_residual_summary IS
    'Stores residual quantiles (abs_p90/abs_p95) and MdAPE per item/horizon from rolling-origin CV.';

COMMENT ON TABLE analytics.forecast_item_month IS
    'Latest run forecasts (p50/p10/p90) per item, horizon, and period.';

COMMENT ON TABLE analytics.forecast_run IS
    'Metadata for forecasting pipeline runs orchestrated via the FastAPI endpoints.';

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

COMMENT ON TABLE analytics.forecast_alert IS
    'Threshold and drift alerts emitted by the forecasting pipeline.';
