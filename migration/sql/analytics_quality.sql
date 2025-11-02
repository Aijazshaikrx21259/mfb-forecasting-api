CREATE TABLE IF NOT EXISTS analytics.item_agency_monthly_actuals (
    month_key text NOT NULL,
    month_start date NOT NULL,
    period_end_date date NOT NULL,
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
    rolling_avg_qty_agency_item numeric(18,4),
    rolling_avg_qty_item numeric(18,4),
    baseline_qty numeric(18,4),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (month_key, agency_internal_id, item_id)
);

TRUNCATE TABLE analytics.item_agency_monthly_actuals;

WITH ordered AS (
    SELECT
        s.month_key,
        cal.period_start_date,
        cal.period_end_date,
        s.agency_internal_id,
        s.agency_name,
        s.item_id,
        s.item_name,
        s.sum_quantity,
        s.sum_weight,
        s.sum_cost,
        s.count_transactions,
        s.max_status_description,
        s.data_source,
        AVG(NULLIF(s.sum_quantity, 0)) OVER (
            PARTITION BY s.agency_internal_id, s.item_id
            ORDER BY cal.period_start_date
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS rolling_avg_qty_agency_item,
        AVG(NULLIF(s.sum_quantity, 0)) OVER (
            PARTITION BY s.item_id
            ORDER BY cal.period_start_date
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS rolling_avg_qty_item
    FROM core.monthly_item_agency_snapshot s
    JOIN core.dim_calendar_month cal ON cal.month_key = s.month_key
)
INSERT INTO analytics.item_agency_monthly_actuals (
    month_key,
    month_start,
    period_end_date,
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
    rolling_avg_qty_agency_item,
    rolling_avg_qty_item,
    baseline_qty,
    updated_at
)
SELECT
    o.month_key,
    o.period_start_date AS month_start,
    o.period_end_date,
    o.agency_internal_id,
    o.agency_name,
    o.item_id,
    o.item_name,
    o.sum_quantity,
    o.sum_weight,
    o.sum_cost,
    o.count_transactions,
    o.max_status_description,
    o.data_source,
    o.rolling_avg_qty_agency_item,
    o.rolling_avg_qty_item,
    COALESCE(o.rolling_avg_qty_agency_item, o.rolling_avg_qty_item, o.sum_quantity) AS baseline_qty,
    now() AS updated_at
FROM ordered o;

TRUNCATE TABLE analytics.system_anomaly_candidates;

WITH base AS (
    SELECT
        a.month_key,
        a.month_start,
        a.agency_internal_id,
        a.item_id,
        a.sum_quantity,
        a.baseline_qty,
        a.rolling_avg_qty_agency_item,
        a.rolling_avg_qty_item,
        a.count_transactions,
        a.data_source,
        LAG(a.sum_quantity) OVER (
            PARTITION BY a.agency_internal_id, a.item_id
            ORDER BY a.month_start
        ) AS prev_month_qty,
        COUNT(*) FILTER (WHERE a.sum_quantity > 0) OVER (
            PARTITION BY a.agency_internal_id, a.item_id
            ORDER BY a.month_start
            ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
        ) AS shipments_last_6,
        LAG(a.data_source) OVER (
            PARTITION BY a.agency_internal_id, a.item_id
            ORDER BY a.month_start
        ) AS prev_data_source
    FROM analytics.item_agency_monthly_actuals a
),
stockout AS (
    SELECT
        b.month_key,
        b.agency_internal_id,
        b.item_id,
        'STOCKOUT' AS flag_type,
        'AGENCY_ITEM' AS flag_level,
        'Quantity dropped to zero after sustained demand' AS flag_reason,
        'stockout_candidate' AS detected_rule,
        NULL::numeric(18,4) AS detected_score
    FROM base b
    WHERE b.sum_quantity = 0
      AND b.shipments_last_6 >= 3
      AND COALESCE(b.rolling_avg_qty_agency_item, b.rolling_avg_qty_item, b.baseline_qty) > 0
),
negative_movements AS (
    SELECT
        b.month_key,
        b.agency_internal_id,
        b.item_id,
        'ANOMALY' AS flag_type,
        'AGENCY_ITEM' AS flag_level,
        'Negative quantity after positive month' AS flag_reason,
        'negative_movement' AS detected_rule,
        NULL::numeric(18,4) AS detected_score
    FROM base b
    WHERE b.sum_quantity < 0
      AND COALESCE(b.prev_month_qty, 0) > 0
),
volume_spikes AS (
    SELECT
        b.month_key,
        b.agency_internal_id,
        b.item_id,
        'ANOMALY' AS flag_type,
        'AGENCY_ITEM' AS flag_level,
        'Volume deviates more than 70% from baseline' AS flag_reason,
        'volume_spike_drop' AS detected_rule,
        CASE
            WHEN COALESCE(b.baseline_qty, 0) = 0 THEN NULL
            ELSE ABS(b.sum_quantity - b.baseline_qty) / NULLIF(b.baseline_qty, 0)
        END AS detected_score
    FROM base b
    WHERE COALESCE(b.baseline_qty, 0) > 0
      AND ABS(b.sum_quantity - b.baseline_qty) / NULLIF(b.baseline_qty, 0) > 0.7
),
load_profile AS (
    SELECT
        agg.month_key,
        agg.month_start,
        agg.load_batches,
        agg.total_records,
        AVG(agg.total_records) OVER (
            ORDER BY agg.month_start
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ) AS avg_prev_records
    FROM (
        SELECT
            lb.month_key,
            to_date(lb.month_key || '-01', 'YYYY-MM-DD') AS month_start,
            COUNT(*) AS load_batches,
            SUM(lb.record_count) AS total_records
        FROM stg.load_batch_log lb
        WHERE lb.month_key IS NOT NULL
        GROUP BY lb.month_key
    ) agg
),
partial_period AS (
    SELECT
        lp.month_key,
        NULL::text AS agency_internal_id,
        NULL::text AS item_id,
        'PARTIAL_PERIOD' AS flag_type,
        'GLOBAL' AS flag_level,
        'Multiple small loads or record count drop detected' AS flag_reason,
        'partial_period' AS detected_rule,
        lp.total_records::numeric(18,4) AS detected_score
    FROM load_profile lp
    WHERE lp.load_batches > 1
       OR (lp.avg_prev_records IS NOT NULL AND lp.total_records < lp.avg_prev_records * 0.6)
),
source_change AS (
    SELECT
        b.month_key,
        b.agency_internal_id,
        b.item_id,
        'BAD_DATA' AS flag_type,
        'AGENCY_ITEM' AS flag_level,
        'Source system changed compared to previous month' AS flag_reason,
        'source_change' AS detected_rule,
        NULL::numeric(18,4) AS detected_score
    FROM base b
    WHERE b.prev_data_source IS NOT NULL
      AND b.prev_data_source <> b.data_source
)
INSERT INTO analytics.system_anomaly_candidates (
    month_key,
    agency_internal_id,
    item_id,
    flag_type,
    flag_level,
    flag_reason,
    detected_rule,
    detected_score
)
SELECT * FROM stockout
UNION ALL
SELECT * FROM negative_movements
UNION ALL
SELECT * FROM volume_spikes
UNION ALL
SELECT * FROM partial_period
UNION ALL
SELECT * FROM source_change;

WITH candidate_issue AS (
    SELECT
        c.month_key,
        c.agency_internal_id,
        c.item_id,
        c.flag_type,
        c.flag_level,
        c.flag_reason,
        c.detected_rule,
        md5(
            coalesce('analytics.system_anomaly_candidates', '') || '|' ||
            coalesce(c.flag_type, '') || '|' ||
            coalesce(c.flag_level, '') || '|' ||
            coalesce(c.month_key, '') || '|' ||
            coalesce(c.agency_internal_id, '') || '|' ||
            coalesce(c.item_id, '') || '|' ||
            'SYSTEM'
        ) AS issue_hash
    FROM analytics.system_anomaly_candidates c
)
INSERT INTO core.data_quality_issue (
    source_table,
    issue_type,
    issue_scope,
    month_key,
    agency_internal_id,
    item_id,
    detected_by,
    detected_at_utc,
    detected_rule,
    notes
)
SELECT
    'analytics.system_anomaly_candidates' AS source_table,
    ci.flag_type AS issue_type,
    CASE
        WHEN ci.flag_level = 'GLOBAL' THEN 'MONTH'
        WHEN ci.flag_level = 'AGENCY' THEN 'AGENCY_MONTH'
        WHEN ci.flag_level = 'ITEM' THEN 'ITEM_MONTH'
        ELSE 'AGENCY_ITEM_MONTH'
    END AS issue_scope,
    ci.month_key,
    ci.agency_internal_id,
    ci.item_id,
    'SYSTEM' AS detected_by,
    now() AS detected_at_utc,
    ci.detected_rule,
    ci.flag_reason AS notes
FROM candidate_issue ci
ON CONFLICT (issue_hash) DO UPDATE
SET
    detected_at_utc = EXCLUDED.detected_at_utc,
    detected_rule = EXCLUDED.detected_rule,
    notes = EXCLUDED.notes;

UPDATE analytics.month_quality_flag
SET is_active = FALSE,
    flagged_at_utc = now()
WHERE flagged_by = 'SYSTEM';

INSERT INTO analytics.month_quality_flag (
    month_key,
    agency_internal_id,
    item_id,
    flag_type,
    flag_level,
    flag_reason,
    flagged_by,
    detected_issue_id,
    is_active
)
SELECT
    c.month_key,
    c.agency_internal_id,
    c.item_id,
    c.flag_type,
    c.flag_level,
    c.flag_reason,
    'SYSTEM' AS flagged_by,
    i.dq_issue_id,
    TRUE AS is_active
FROM analytics.system_anomaly_candidates c
LEFT JOIN core.data_quality_issue i ON i.issue_hash = md5(
    coalesce('analytics.system_anomaly_candidates', '') || '|' ||
    coalesce(c.flag_type, '') || '|' ||
    coalesce(c.flag_level, '') || '|' ||
    coalesce(c.month_key, '') || '|' ||
    coalesce(c.agency_internal_id, '') || '|' ||
    coalesce(c.item_id, '') || '|' ||
    'SYSTEM'
)
ON CONFLICT (scope_key) DO UPDATE
SET
    flag_reason = EXCLUDED.flag_reason,
    flagged_at_utc = now(),
    detected_issue_id = EXCLUDED.detected_issue_id,
    is_active = TRUE;

CREATE OR REPLACE VIEW analytics.v_forecast_training_base AS
SELECT
    a.*
FROM analytics.item_agency_monthly_actuals a
WHERE NOT EXISTS (
    SELECT 1
    FROM analytics.month_quality_flag f
    WHERE f.is_active = TRUE
      AND f.month_key = a.month_key
      AND (f.agency_internal_id IS NULL OR f.agency_internal_id = a.agency_internal_id)
      AND (f.item_id IS NULL OR f.item_id = a.item_id)
);


