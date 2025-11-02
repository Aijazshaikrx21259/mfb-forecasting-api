CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.item_monthly_purchases AS
SELECT
    item_id,
    date_trunc(
        'month',
        COALESCE(
            accounting_period_start_date::timestamptz,
            createdfrom_transaction_date::timestamptz
        )
    )::date AS month,
    SUM(quantity)::numeric(18,4) AS quantity,
    SUM(total_cost)::numeric(18,4) AS total_cost,
    COUNT(*) AS transaction_count
FROM core.fact_goods_distributed
WHERE item_id IS NOT NULL
  AND COALESCE(accounting_period_start_date, createdfrom_transaction_date) IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
