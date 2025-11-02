# Excel → Neon Migration Toolkit

This directory contains a Typer-based CLI that ingests ERP extracts delivered as Excel workbooks, stages them in Neon Postgres, and builds forecasting-friendly tables/views.

## Prerequisites

- Python 3.10+ with `pip`.
- Neon database provisioned (test or production). Copy its connection string.
- Local `.env` (based on `.env.example`) with `NEON_DATABASE_URL=postgresql+psycopg2://...`.
- Python dependencies:
  ```bash
  python -m pip install -r migration/requirements.txt
  ```

Optional: create a virtual environment before installing packages.

## Configuration (`migration/config.yaml`)

`config.yaml` maps Excel sheets to staging tables and stores metadata used throughout the workflow.

- `defaults.*` – fallbacks for chunk size, row-count threshold, etc.
- `tables.<schema.table>` – per-sheet settings:
  - `file` / `sheet` – default Excel source.
  - `columns` – sanitized column names → `{source: "Original Header", type: "sql_type"}`.
  - `pk` / `upsert_keys` – optional; define when reliable uniqueness exists.
  - `incremental_key` – optional timestamp/date column for incremental loading.
  - `allow_new_columns` – enable auto `ALTER TABLE ADD COLUMN` when new headers appear.

Run `infer` any time the Excel structure changes; it updates `config.yaml` automatically (or the file path specified via `--save-overrides`).

## CLI Overview

All commands run from repo root (or supply `--config`/`--sql-path` as needed):

### Quick run sequence

```bash
# 1. Load Neon connection string (or `source migration/.env`)
export $(cat migration/.env | xargs)

# 2. Create schemas and helper tables
python migration/load_excel_to_neon.py init-db

# 3. Infer column metadata (update config.yaml)
python migration/load_excel_to_neon.py infer \
  --file "migration/data/Goods Distributed View.xlsx" \
  --sheet "Goods Distributed View" \
  --table stg.erp_goods_distributed \
  --save-overrides migration/config.yaml

# 4. Ensure staging table structure
python migration/load_excel_to_neon.py create-staging \
  --table stg.erp_goods_distributed

# 5. Load Excel data (full refresh) using config defaults
python migration/load_excel_to_neon.py load-staging \
  --table stg.erp_goods_distributed \
  --mode full

# 6. Promote to core + build analytics
python migration/load_excel_to_neon.py promote-core
python migration/load_excel_to_neon.py build-analytics
```

To reset schemas/tables before rerunning:

```bash
python migration/load_excel_to_neon.py reset-data \
  --truncate-staging \
  --truncate-core \
  --drop-analytics-view
```

Use `--mode incremental` only after defining a reliable key in `config.yaml` or via CLI overrides. Regardless of mode, each run logs a checksum row in `stg.load_batch_log` so the analytics step can flag partial periods automatically.

1. **Bootstrap schemas + quality control tables**

   ```bash
   python migration/load_excel_to_neon.py init-db
   ```

   Creates `stg`, `core`, `analytics`, helper table `stg._column_name_map`, the new `stg.load_batch_log`, and quality objects (`core.dim_calendar_month`, `core.data_quality_issue`, `analytics.month_quality_flag`, `analytics.system_anomaly_candidates`).

2. **Infer column metadata**

   ```bash
   python migration/load_excel_to_neon.py infer \
     --file "migration/data/Goods Distributed View.xlsx" \
     --sheet "Goods Distributed View" \
     --table stg.erp_goods_distributed \
     --save-overrides migration/config.yaml
   ```

   - Prints inferred column types + sample rows.
   - Writes header/type mapping to YAML (overrides existing entries).

3. **Create/Evolve staging table**

   ```bash
   python migration/load_excel_to_neon.py create-staging \
     --table stg.erp_goods_distributed
   ```

   - Builds the table structure in `stg`.
   - Ensures PK/unique constraints (based on config).
   - Loads header mappings into `stg._column_name_map`.

4. **Load data (with batch logging)**

   ```bash
   python migration/load_excel_to_neon.py load-staging \
     --file "migration/data/Goods Distributed View.xlsx" \
     --sheet "Goods Distributed View" \
     --table stg.erp_goods_distributed \
     --mode full
   ```

   - Full refresh truncates and reloads using PostgreSQL `COPY` in 50k-row chunks and records a summary row in `stg.load_batch_log` (month key, source file, record count, checksum) so partial periods and schema drifts can be detected later in analytics.
   - Switch to `--mode incremental` only after defining keys in the config or via CLI flags.
   - Keep commands on a single line (or escape newlines with `\`) when paths contain spaces like `"Goods Distributed View.xlsx"`.
   - Flags:
     - `--allow-new-columns` auto-adds new headers (updates config + table).
     - `--validate-only` runs checks without writing.
     - `--dry-run` prints load plan and exits.
     - `--force` bypasses row-count sanity guard.

5. **Promote to core schema + build monthly snapshot**
   ```bash
   python migration/load_excel_to_neon.py promote-core
   ```
   Executes `sql/promote_core.sql` followed by `sql/build_core_summaries.sql`:
   - Copies rows from `stg.erp_goods_distributed` into `core.fact_goods_distributed`.
   - Adds derived columns (`transaction_date`, `transaction_month_start`, `month_key`, `agency_internal_id`, `is_negative_movement`, `is_zero_or_missing_qty`).
   - Builds `core.monthly_item_agency_snapshot`, the aggregated table used for anomaly detection and baseline calculations.

- Trims text columns, casts numerics, normalises `transaction_date` to `date` when present.
- Maintains a unique index on `(item_id, transaction_date)` when those columns exist.

6. **Build analytics layer + anomaly candidates**

```bash
python migration/load_excel_to_neon.py build-analytics
```

Runs the analytics stage in four parts:

- Maintains calendar helpers `core.dim_month` and `core.dim_calendar_month` (generate_series up to 12–18 months ahead).
- Refreshes `core.dim_item` with `first_seen_at` / `last_seen_at` metadata and activity flags.
- Rebuilds `analytics.item_month_demand` plus the legacy `analytics.item_monthly_purchases` view.
- Populates the quality layer: `analytics.item_agency_monthly_actuals`, `analytics.system_anomaly_candidates`, merges system flags into `analytics.month_quality_flag`, and refreshes the training view `analytics.v_forecast_training_base`.

The command emits a JSON summary containing the `build_run_id`, item/month counts, and the min/max month range produced so CI jobs can assert row volumes.

7. **Reset data (optional)**

```bash
python migration/load_excel_to_neon.py reset-data \
  --truncate-staging \
  --truncate-core \
  --truncate-demand \
  --keep-analytics-view
```

- Truncates `stg.erp_goods_distributed`, `core.fact_goods_distributed`, and (by default) `analytics.item_month_demand`.
- Drops `analytics.item_monthly_purchases` unless `--keep-analytics-view` is provided.
- Add `--truncate-dims` if you need to rebuild the dimension helpers from scratch.

## Validations & Safeguards

- **Header checks** – incoming sanitized headers must match config unless `--allow-new-columns`.
- **Column mapping** – `stg._column_name_map` tracks original → sanitized names for lineage.
- **Null guard** – required key columns must be non-null.
- **Duplicate guard** – when keys are defined, batches with duplicate key values are rejected.
- **Row-count sanity** – aborts if a batch <50% of previous load unless `--force`.
- **Date guard** – incremental loads must fall within `date_tolerance_days` of existing data.

Failures raise descriptive errors and exit with non-zero status so CI/CD can detect issues.

## Incremental Run Example

Once you establish a trusted key + incremental column (either in `config.yaml` or via CLI arguments), you can switch to incremental mode. Example placeholder:

```bash
python migration/load_excel_to_neon.py load-staging \
  --table stg.erp_goods_distributed \
  --mode incremental \
  --incremental-key YOUR_INCREMENTAL_COLUMN \
  --pk key_col1,key_col2
python migration/load_excel_to_neon.py promote-core
python migration/load_excel_to_neon.py build-analytics
```

Use `--dry-run` first when new columns appear or when testing a new extract.

## Verify row counts

After a load, you can confirm the Excel file landed in each layer:

```sql
SELECT COUNT(*) FROM stg.erp_goods_distributed;
SELECT COUNT(*) FROM core.fact_goods_distributed;
SELECT COUNT(*) FROM analytics.item_month_demand;
SELECT COUNT(*) FROM analytics.item_monthly_purchases;
```

All staging/core counts should match the Excel row total (56,794 in the sample file), while the analytics view reflects the monthly aggregation.

## Troubleshooting Tips

- **Authentication errors** – ensure `NEON_DATABASE_URL` has `sslmode=require` and reachable host.
- **Missing Excel engine** – install `openpyxl`.
- **New headers** – rerun `infer` with the latest workbook to refresh `config.yaml`.
- **Column type mismatches** – edit `config.yaml` to override (`type: numeric(18,4)` etc.), then rerun `create-staging`.
- **Performance** – adjust `defaults.chunk_size` if you routinely load >50k rows; leave enough memory for buffering.

## CI/CD & Automation

- Store real secrets in `migration/.env` (ignored by default). Use `.env.example` as documentation only.
- Invoke the CLI from scheduled jobs or CI pipelines to refresh the Neon database.
- Combine `--dry-run` / `--validate-only` with pipeline steps to guard against malformed extracts before production loads.
