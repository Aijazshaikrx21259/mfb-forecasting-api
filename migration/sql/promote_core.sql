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
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS fact_goods_distributed_item_transaction_idx '
             || 'ON core.fact_goods_distributed (item_id, transaction_date)';
    END IF;
END $$;
