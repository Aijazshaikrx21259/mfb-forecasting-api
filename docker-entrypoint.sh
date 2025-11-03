#!/bin/bash
set -euo pipefail

check_database_ready() {
  local retries=0
  local max_retries=60
  local delay=2

  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[entrypoint] DATABASE_URL not set; skipping database checks."
    return 1
  fi

  echo "[entrypoint] Waiting for database to become available..."
  until psql "${DATABASE_URL}" -c "SELECT 1" >/dev/null 2>&1; do
    retries=$((retries + 1))
    if (( retries >= max_retries )); then
      echo "[entrypoint] Failed to connect to database after $((retries * delay)) seconds."
      return 1
    fi
    sleep "${delay}"
  done

  echo "[entrypoint] Database is available."
  return 0
}

run_stub_migration() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[entrypoint] DATABASE_URL not set; skipping stub migration."
    return
  fi

  local forecast_stub="/app/migration/sql/local_forecast_stub.sql"
  local backtest_stub="/app/migration/sql/local_backtest_stub.sql"
  local sample_data="/app/migration/sql/populate_sample_backtest_data.sql"

  if [[ -f "${forecast_stub}" ]]; then
    echo "[entrypoint] Applying local forecast stub migration..."
    psql "${DATABASE_URL}" -f "${forecast_stub}" >/dev/null
    echo "[entrypoint] Forecast stub migration applied."
  fi

  if [[ -f "${backtest_stub}" ]]; then
    echo "[entrypoint] Applying local backtest stub migration..."
    psql "${DATABASE_URL}" -f "${backtest_stub}" >/dev/null
    echo "[entrypoint] Backtest stub migration applied."
  fi

  if [[ -f "${sample_data}" ]]; then
    echo "[entrypoint] Populating sample backtest data..."
    psql "${DATABASE_URL}" -f "${sample_data}" >/dev/null 2>&1 || echo "[entrypoint] Sample data already exists or failed to insert."
    echo "[entrypoint] Sample data population complete."
  fi
}

if check_database_ready; then
  run_stub_migration || true
else
  echo "[entrypoint] Continuing without database initialisation."
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
