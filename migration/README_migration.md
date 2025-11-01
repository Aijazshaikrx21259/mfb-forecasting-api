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
  --file "data/Goods Distributed View.xlsx" \
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

Use `--mode incremental` only after defining a reliable key in `config.yaml` or via CLI overrides.

1. **Bootstrap schemas**  
   ```bash
   python migration/load_excel_to_neon.py init-db
   ```
   Creates `stg`, `core`, `analytics`, and helper table `stg._column_name_map`.

2. **Infer column metadata**  
   ```bash
   python migration/load_excel_to_neon.py infer \
     --file "data/Goods Distributed View.xlsx" \
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

4. **Load data**  
   ```bash
   python migration/load_excel_to_neon.py load-staging \
     --file "data/Goods Distributed View.xlsx" \
     --sheet "Goods Distributed View" \
     --table stg.erp_goods_distributed \
     --mode full
   ```
   - Full refresh truncates and reloads using PostgreSQL `COPY` in 50k-row chunks.
   - Switch to `--mode incremental` only after defining keys in the config or via CLI flags.
   - Keep commands on a single line (or escape newlines with `\`) when paths contain spaces like `"Goods Distributed View.xlsx"`.
   - Flags:
     - `--allow-new-columns` auto-adds new headers (updates config + table).
     - `--validate-only` runs checks without writing.
     - `--dry-run` prints load plan and exits.
     - `--force` bypasses row-count sanity guard.

5. **Promote to core schema**  
   ```bash
   python migration/load_excel_to_neon.py promote-core
   ```
   Executes `sql/promote_core.sql`:
   - Copies rows from `stg.erp_goods_distributed` into `core.fact_goods_distributed`.
  - Trims text columns, casts numerics, normalises `transaction_date` to `date` when present.
  - Maintains a unique index on `(item_id, transaction_date)` when those columns exist.

6. **Build analytics view**  
   ```bash
   python migration/load_excel_to_neon.py build-analytics
   ```
   Runs `sql/analytics.sql`, creating `analytics.item_monthly_purchases`:
   - Monthly `SUM(quantity)` / `SUM(total_cost)` per `item_id`.
   - Uses `accounting_period_start_date` (or falls back to `createdfrom_transaction_date`) for calendar month.
   - Includes a `transaction_count` metric for monitoring.

7. **Reset data (optional)**  
   ```bash
   python migration/load_excel_to_neon.py reset-data
   ```
   - Truncates `stg.erp_goods_distributed` and `core.fact_goods_distributed`.
   - Drops `analytics.item_monthly_purchases` so the next `build-analytics` recreates it.
   - Toggle behaviour with `--no-truncate-staging`, `--no-truncate-core`, or `--keep-analytics-view`.

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
