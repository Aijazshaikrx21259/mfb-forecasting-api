CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.dim_month (
    month_start date PRIMARY KEY,
    month_key integer NOT NULL,
    year integer NOT NULL,
    month_no integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

WITH bounds AS (
    SELECT
        date_trunc('month', MIN(src_month))::date AS min_month,
        date_trunc('month', MAX(src_month))::date AS max_month
    FROM (
        SELECT
            COALESCE(
                accounting_period_start_date::timestamptz,
                createdfrom_transaction_date::timestamptz
            )::date AS src_month
        FROM core.fact_goods_distributed
        WHERE COALESCE(accounting_period_start_date, createdfrom_transaction_date) IS NOT NULL
    ) fact
), calendar_range AS (
    SELECT
        COALESCE(
            min_month,
            (date_trunc('month', now()) - INTERVAL '12 months')::date
        ) AS start_month,
        (
            COALESCE(max_month, date_trunc('month', now())::date)
            + INTERVAL '18 months'
        )::date AS end_month
    FROM bounds
), series AS (
    SELECT generate_series(start_month, end_month, INTERVAL '1 month')::date AS month_start
    FROM calendar_range
)
INSERT INTO core.dim_month (month_start, month_key, year, month_no, created_at, updated_at)
SELECT
    s.month_start,
    to_char(s.month_start, 'YYYYMM')::integer AS month_key,
    EXTRACT(YEAR FROM s.month_start)::integer AS year,
    EXTRACT(MONTH FROM s.month_start)::integer AS month_no,
    now() AS created_at,
    now() AS updated_at
FROM series s
ON CONFLICT (month_start) DO UPDATE
SET
    month_key = EXCLUDED.month_key,
    year = EXCLUDED.year,
    month_no = EXCLUDED.month_no,
    updated_at = now();

