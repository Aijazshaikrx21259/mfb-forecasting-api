# MFB Forecasting API

API for MFB forecasting functionality with data migration capabilities.

## Project Structure

This repository contains:
- **Main API**: Core forecasting functionality
- **Migration Toolkit**: Excel-to-Neon data migration system located in `migration/`

## Migration Toolkit

The `migration/` directory contains a Typer-based CLI that ingests ERP extracts delivered as Excel workbooks, stages them in Neon Postgres, and builds forecasting-friendly tables/views.

### Quick Start for Migration

1. Navigate to the migration directory and install dependencies:
   ```bash
   cd migration/
   pip install -r requirements.txt
   ```

2. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your Neon database connection string
   ```

3. Run the migration process:
   ```bash
   # Load Neon connection string
   export $(cat migration/.env | xargs)

   # Initialize database schemas
   python migration/load_excel_to_neon.py init-db

   # Load Excel data (update paths to use migration/data/ folder)
   python migration/load_excel_to_neon.py load-staging \
     --file "migration/data/Goods Distributed View.xlsx" \
     --sheet "Goods Distributed View" \
     --table stg.erp_goods_distributed \
     --mode full

   # Promote to core and build analytics
   python migration/load_excel_to_neon.py promote-core
   python migration/load_excel_to_neon.py build-analytics
   ```

For detailed documentation on the migration process, see [`migration/README_migration.md`](migration/README_migration.md).

## Configuration

- Main configuration: [`migration/config.yaml`](migration/config.yaml)
- Environment variables: [`migration/.env.example`](migration/.env.example)
- Database schemas: [`migration/sql/`](migration/sql/)
  - Core promotion logic: [`migration/sql/promote_core.sql`](migration/sql/promote_core.sql)
  - Analytics view: [`migration/sql/analytics.sql`](migration/sql/analytics.sql)

## Requirements

- Python 3.10+
- Neon database (PostgreSQL)
- Excel files for data ingestion
