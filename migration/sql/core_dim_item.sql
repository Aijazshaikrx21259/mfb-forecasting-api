CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.dim_item (
    item_id text PRIMARY KEY,
    item_name text,
    first_seen_at timestamptz,
    last_seen_at timestamptz,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

WITH src AS (
    SELECT
        item_id::text AS item_id,
        MAX(NULLIF(item_name, '')) FILTER (WHERE item_name IS NOT NULL) AS item_name,
        MIN(
            COALESCE(
                accounting_period_start_date::timestamptz,
                createdfrom_transaction_date::timestamptz
            )
        ) AS first_seen_at,
        MAX(
            COALESCE(
                accounting_period_start_date::timestamptz,
                createdfrom_transaction_date::timestamptz
            )
        ) AS last_seen_at
    FROM core.fact_goods_distributed
    WHERE item_id IS NOT NULL
    GROUP BY item_id
),
prepared AS (
    SELECT
        item_id,
        item_name,
        first_seen_at,
        last_seen_at,
        CASE
            WHEN last_seen_at IS NULL THEN false
            WHEN last_seen_at >= now() - INTERVAL '18 months' THEN true
            ELSE false
        END AS is_active
    FROM src
)
INSERT INTO core.dim_item (item_id, item_name, first_seen_at, last_seen_at, is_active, created_at, updated_at)
SELECT
    p.item_id,
    p.item_name,
    p.first_seen_at,
    p.last_seen_at,
    COALESCE(p.is_active, false),
    now(),
    now()
FROM prepared p
ON CONFLICT (item_id) DO UPDATE
SET
    item_name = COALESCE(EXCLUDED.item_name, core.dim_item.item_name),
    first_seen_at = COALESCE(
        LEAST(core.dim_item.first_seen_at, EXCLUDED.first_seen_at),
        COALESCE(core.dim_item.first_seen_at, EXCLUDED.first_seen_at)
    ),
    last_seen_at = COALESCE(
        GREATEST(core.dim_item.last_seen_at, EXCLUDED.last_seen_at),
        COALESCE(core.dim_item.last_seen_at, EXCLUDED.last_seen_at)
    ),
    is_active = EXCLUDED.is_active,
    updated_at = now();

