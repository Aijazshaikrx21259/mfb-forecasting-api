CREATE TABLE IF NOT EXISTS core.monthly_item_agency_snapshot (
    month_key text NOT NULL,
    month_start date NOT NULL,
    agency_internal_id text,
    agency_name text,
    item_id text NOT NULL,
    item_name text,
    sum_quantity numeric(18,4) NOT NULL,
    sum_weight numeric(18,4),
    sum_cost numeric(18,4),
    count_transactions integer NOT NULL,
    max_status_description text,
    data_source text,
    last_updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (month_key, agency_internal_id, item_id)
);

TRUNCATE TABLE core.monthly_item_agency_snapshot;

WITH base AS (
    SELECT
        f.month_key,
        f.transaction_month_start,
        COALESCE(f.agency_internal_id, NULLIF(f.agency_account_number, '')) AS agency_internal_id,
        MAX(NULLIF(f.agency_name, '')) FILTER (WHERE f.agency_name IS NOT NULL) AS agency_name,
        f.item_id,
        MAX(NULLIF(f.item_name, '')) FILTER (WHERE f.item_name IS NOT NULL) AS item_name,
        SUM(COALESCE(f.quantity, 0))::numeric(18,4) AS sum_quantity,
        SUM(COALESCE(f.total_weight, 0))::numeric(18,4) AS sum_weight,
        SUM(COALESCE(f.total_cost, 0))::numeric(18,4) AS sum_cost,
        COUNT(*)::integer AS count_transactions,
        MAX(f.status_description) AS max_status_description,
        MAX(f.data_source) AS data_source
    FROM core.fact_goods_distributed f
    WHERE f.item_id IS NOT NULL
      AND f.transaction_month_start IS NOT NULL
    GROUP BY
        f.month_key,
        f.transaction_month_start,
        COALESCE(f.agency_internal_id, NULLIF(f.agency_account_number, '')),
        f.item_id
)
INSERT INTO core.monthly_item_agency_snapshot (
    month_key,
    month_start,
    agency_internal_id,
    agency_name,
    item_id,
    item_name,
    sum_quantity,
    sum_weight,
    sum_cost,
    count_transactions,
    max_status_description,
    data_source,
    last_updated_at
)
SELECT
    b.month_key,
    b.transaction_month_start AS month_start,
    b.agency_internal_id,
    b.agency_name,
    b.item_id,
    b.item_name,
    b.sum_quantity,
    b.sum_weight,
    b.sum_cost,
    b.count_transactions,
    b.max_status_description,
    b.data_source,
    now() AS last_updated_at
FROM base b;


