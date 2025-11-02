CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS stg.load_batch_log (
    load_batch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name text NOT NULL,
    source_file_name text,
    loaded_at_utc timestamptz NOT NULL DEFAULT now(),
    record_count integer NOT NULL,
    load_mode text NOT NULL,
    period_detected text,
    month_key text,
    checksum text,
    metadata jsonb DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS core.dim_calendar_month (
    month_key text PRIMARY KEY,
    accounting_period_name text,
    period_start_date date NOT NULL,
    period_end_date date NOT NULL,
    calendar_year integer NOT NULL,
    calendar_month integer NOT NULL,
    data_source text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.data_quality_issue (
    dq_issue_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_table text NOT NULL,
    issue_type text NOT NULL,
    issue_scope text NOT NULL,
    month_key text,
    agency_internal_id text,
    item_id text,
    detected_by text NOT NULL,
    detected_at_utc timestamptz NOT NULL DEFAULT now(),
    detected_rule text,
    notes text,
    issue_hash text GENERATED ALWAYS AS (
        md5(
            coalesce(source_table, '') || '|' ||
            coalesce(issue_type, '') || '|' ||
            coalesce(issue_scope, '') || '|' ||
            coalesce(month_key, '') || '|' ||
            coalesce(agency_internal_id, '') || '|' ||
            coalesce(item_id, '') || '|' ||
            coalesce(detected_by, '')
        )
    ) STORED,
    UNIQUE(issue_hash)
);

CREATE TABLE IF NOT EXISTS analytics.month_quality_flag (
    flag_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    month_key text NOT NULL,
    agency_internal_id text,
    item_id text,
    flag_type text NOT NULL,
    flag_level text NOT NULL,
    flag_reason text,
    flagged_by text NOT NULL,
    flagged_at_utc timestamptz NOT NULL DEFAULT now(),
    expires_at_utc timestamptz,
    is_active boolean NOT NULL DEFAULT TRUE,
    detected_issue_id uuid,
    scope_key text GENERATED ALWAYS AS (
        (
            (((month_key || '::' || coalesce(agency_internal_id, '*')) || '::' || coalesce(item_id, '*'))
            || '::' || flag_type) || '::' || flagged_by
        )
    ) STORED,
    UNIQUE(scope_key)
);

CREATE INDEX IF NOT EXISTS month_quality_flag_active_idx
    ON analytics.month_quality_flag (month_key, is_active);

CREATE TABLE IF NOT EXISTS analytics.system_anomaly_candidates (
    candidate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    month_key text NOT NULL,
    agency_internal_id text,
    item_id text,
    flag_type text NOT NULL,
    flag_level text NOT NULL,
    flag_reason text,
    detected_rule text,
    detected_score numeric(18,4),
    detected_at_utc timestamptz NOT NULL DEFAULT now(),
    source_table text NOT NULL DEFAULT 'analytics.item_agency_monthly_actuals'
);


