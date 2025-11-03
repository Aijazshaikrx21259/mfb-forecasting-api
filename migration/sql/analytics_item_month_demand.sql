CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.item_month_demand (
    item_id text NOT NULL,
    item_name text,
    month_start date NOT NULL,
    demand numeric(18,4) NOT NULL,
    demand_raw numeric(18,4) NOT NULL,
    demand_abs numeric(18,4) NOT NULL,
    source_system text NOT NULL DEFAULT 'ERP',
    is_synthetic boolean NOT NULL,
    clamped_to_zero boolean NOT NULL,
    build_run_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, month_start)
);

TRUNCATE TABLE analytics.item_month_demand;

WITH params AS (
    SELECT CAST(:build_run_id AS uuid) AS build_run_id
), src AS (
    SELECT
        f.item_id::text AS item_id,
        date_trunc(
            'month',
            COALESCE(
                f.accounting_period_start_date::timestamptz,
                f.createdfrom_transaction_date::timestamptz
            )
        )::date AS month_start,
        MAX(NULLIF(f.item_name, '')) FILTER (WHERE f.item_name IS NOT NULL) AS item_name,
        SUM(COALESCE(f.quantity, 0))::numeric(18,4) AS signed_quantity,
        SUM(ABS(COALESCE(f.quantity, 0)))::numeric(18,4) AS abs_quantity
    FROM core.fact_goods_distributed f
    WHERE f.item_id IS NOT NULL
      AND COALESCE(f.accounting_period_start_date, f.createdfrom_transaction_date) IS NOT NULL
    GROUP BY f.item_id, month_start
), month_window AS (
    SELECT
        COALESCE(MIN(month_start), date_trunc('month', now())::date) AS min_month,
        GREATEST(
            COALESCE(MAX(month_start), date_trunc('month', now())::date),
            (date_trunc('month', now()) + INTERVAL '4 months')::date
        ) AS max_month
    FROM src
), calendar AS (
    SELECT m.month_start
    FROM core.dim_month m
    WHERE m.month_start BETWEEN (SELECT min_month FROM month_window)
        AND (SELECT max_month FROM month_window)
), item_list AS (
    SELECT
        di.item_id,
        di.item_name,
        di.first_seen_at,
        di.last_seen_at,
        di.is_active,
        COALESCE(
            date_trunc('month', di.first_seen_at)::date,
            (SELECT min_month FROM month_window)
        ) AS first_month
    FROM core.dim_item di
    WHERE di.last_seen_at IS NOT NULL
), item_month_grid AS (
    SELECT
        il.item_id,
        il.item_name,
        cal.month_start
    FROM item_list il
    CROSS JOIN calendar cal
    WHERE cal.month_start BETWEEN il.first_month AND (SELECT max_month FROM month_window)
), final_rows AS (
    SELECT
        grid.item_id,
        COALESCE(src.item_name, grid.item_name) AS item_name,
        grid.month_start,
        COALESCE(src.signed_quantity, 0) AS signed_quantity,
        COALESCE(src.abs_quantity, 0) AS abs_quantity,
        src.item_id IS NULL AS is_synthetic
    FROM item_month_grid grid
    LEFT JOIN src ON src.item_id = grid.item_id AND src.month_start = grid.month_start
)
INSERT INTO analytics.item_month_demand (
    item_id,
    item_name,
    month_start,
    demand,
    demand_raw,
    demand_abs,
    source_system,
    is_synthetic,
    clamped_to_zero,
    build_run_id,
    created_at,
    updated_at
)
SELECT
    fr.item_id,
    fr.item_name,
    fr.month_start,
    CASE
        WHEN fr.signed_quantity < 0 THEN ABS(fr.signed_quantity)
        ELSE fr.signed_quantity
    END AS demand,
    fr.signed_quantity AS demand_raw,
    fr.abs_quantity AS demand_abs,
    'ERP' AS source_system,
    fr.is_synthetic,
    (fr.signed_quantity < 0) AS clamped_to_zero,
    params.build_run_id,
    now() AS created_at,
    now() AS updated_at
FROM final_rows fr
CROSS JOIN params
ON CONFLICT (item_id, month_start) DO UPDATE
SET
    item_name = EXCLUDED.item_name,
    demand = EXCLUDED.demand,
    demand_raw = EXCLUDED.demand_raw,
    demand_abs = EXCLUDED.demand_abs,
    source_system = EXCLUDED.source_system,
    is_synthetic = EXCLUDED.is_synthetic,
    clamped_to_zero = EXCLUDED.clamped_to_zero,
    build_run_id = EXCLUDED.build_run_id,
    updated_at = now();

CREATE OR REPLACE VIEW analytics.item_month_demand_positive AS
SELECT *
FROM analytics.item_month_demand
WHERE demand > 0;

