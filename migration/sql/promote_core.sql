CREATE SCHEMA IF NOT EXISTS core;

DO $$
DECLARE
    select_list text;
    staging_exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'stg'
          AND table_name = 'erp_goods_distributed'
    )
    INTO staging_exists;

    IF NOT staging_exists THEN
        RAISE EXCEPTION 'Staging table stg.erp_goods_distributed does not exist. Run create-staging first.';
    END IF;

    EXECUTE 'CREATE TABLE IF NOT EXISTS core.fact_goods_distributed '
            ' (LIKE stg.erp_goods_distributed INCLUDING DEFAULTS INCLUDING IDENTITY INCLUDING CONSTRAINTS)';

    EXECUTE 'ALTER TABLE core.fact_goods_distributed '
            'ADD COLUMN IF NOT EXISTS transaction_date date,'
            'ADD COLUMN IF NOT EXISTS transaction_month_start date,'
            'ADD COLUMN IF NOT EXISTS month_key text,'
            'ADD COLUMN IF NOT EXISTS agency_internal_id text,'
            'ADD COLUMN IF NOT EXISTS is_negative_movement boolean,'
            'ADD COLUMN IF NOT EXISTS is_zero_or_missing_qty boolean';

    EXECUTE 'CREATE INDEX IF NOT EXISTS fact_goods_month_key_idx '
            'ON core.fact_goods_distributed (month_key)';

    SELECT string_agg(column_expression, ', ')
    INTO select_list
    FROM (
        SELECT
            CASE
                WHEN column_name = 'transaction_date' AND data_type IN ('timestamp without time zone', 'timestamp with time zone') THEN
                    format('date_trunc(''day'', %1$I::timestamptz)::date AS %1$I', column_name)
                WHEN column_name = 'transaction_date' AND data_type = 'date' THEN
                    format('%1$I::date AS %1$I', column_name)
                WHEN data_type IN ('character varying', 'character', 'text') THEN
                    format('NULLIF(trim(%1$I::text), '''')::text AS %1$I', column_name)
                WHEN data_type = 'numeric' THEN
                    format('%1$I::numeric(18,4) AS %1$I', column_name)
                ELSE
                    format('%1$I AS %1$I', column_name)
            END AS column_expression
        FROM information_schema.columns
        WHERE table_schema = 'stg'
          AND table_name = 'erp_goods_distributed'
        ORDER BY ordinal_position
    ) ordered_columns;

    IF select_list IS NULL THEN
        RAISE EXCEPTION 'No columns discovered for stg.erp_goods_distributed.';
    END IF;

    EXECUTE 'TRUNCATE TABLE core.fact_goods_distributed';
    EXECUTE format(
        'INSERT INTO core.fact_goods_distributed SELECT %s FROM stg.erp_goods_distributed',
        select_list
    );

    EXECUTE $upd$
        UPDATE core.fact_goods_distributed
        SET
            transaction_date = COALESCE(
                createdfrom_transaction_date::timestamptz,
                accounting_period_start_date::timestamptz
            )::date,
            transaction_month_start = date_trunc(
                'month',
                COALESCE(
                    createdfrom_transaction_date::timestamptz,
                    accounting_period_start_date::timestamptz
                )
            )::date,
            month_key = to_char(
                date_trunc(
                    'month',
                    COALESCE(
                        createdfrom_transaction_date::timestamptz,
                        accounting_period_start_date::timestamptz
                    )
                ),
                'YYYY-MM'
            ),
            agency_internal_id = NULLIF(
                trim(
                    trailing '.' from trim(
                        trailing '0' from COALESCE(entity_internal_id::text, '')
                    )
                ),
                ''
            ),
            is_negative_movement = (COALESCE(quantity, 0)::numeric < 0)
                OR (COALESCE(total_weight, 0)::numeric < 0),
            is_zero_or_missing_qty = COALESCE(quantity, 0)::numeric = 0
    $upd$;

    EXECUTE $upd$
        UPDATE core.fact_goods_distributed
        SET agency_internal_id = COALESCE(agency_internal_id, NULLIF(agency_account_number, ''))
        WHERE agency_internal_id IS NULL
    $upd$;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'fact_goods_distributed'
          AND column_name = 'item_id'
    )
    AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'fact_goods_distributed'
          AND column_name = 'transaction_date'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS fact_goods_distributed_item_transaction_idx '
             || 'ON core.fact_goods_distributed (item_id, transaction_date, transaction_internalid)';
    END IF;
END $$;
