# MFB Forecasting API

FastAPI service that exposes forecasting capabilities. The project currently provides a basic health endpoint and is structured to scale with additional routers and domain logic.

## 🚀 Deploy to Render (Free Tier)

This API is ready to deploy to Render's free tier! The service includes data science libraries (pandas, numpy, statsforecast) that exceed Vercel's 250 MB limit, making Render the ideal platform.

**Quick deploy:**
1. Push your code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Create New → Blueprint
4. Connect your repository (Render auto-detects `render.yaml`)
5. Set your environment variables and deploy

## Quick Start (Docker)

The project ships with a `Dockerfile` and `compose.yaml` so you can run it on macOS, Windows, or Linux without installing Python.

1. Build and start the service (first run may take a minute while the image is built):
   ```bash
   docker compose up --build
   ```
2. Visit the interactive Swagger UI at `http://127.0.0.1:8000/docs` (the root URL redirects there automatically) or call the health check at `http://127.0.0.1:8000/health`.

When running locally, set `DATABASE_URL` to the Neon Postgres connection string if you plan to use the data-quality endpoints. The FastAPI service logs a warning and returns HTTP 503 for those endpoints when the variable is missing.

To stop the containers press `Ctrl+C` and optionally remove them with `docker compose down`.

### Configure security

Endpoints and API documentation require an `X-API-Key` header when an API key is configured. Copy the sample environment file and adjust values to match your trusted clients (for example, your frontend and localhost):

```bash
cp env.example .env
# edit .env to set API_KEY, ALLOWED_ORIGINS, and DATABASE_URL
```

Then export those variables before launching or let Docker Compose read them automatically. When you deploy to production, set `ENVIRONMENT=production` so that requests are only accepted from the `ALLOWED_ORIGINS` allowlist.

```bash
API_KEY=super-secret \
ALLOWED_ORIGINS="https://my-frontend.com" \
ENVIRONMENT=production \
DATABASE_URL=postgresql://user:password@host/database \
docker compose up --build
```

For local development you can skip `ALLOWED_ORIGINS` and keep `ENVIRONMENT=local` (the default); CORS falls back to a wildcard origin to simplify testing. If `API_KEY` is empty, the API remains open regardless of environment.

The `/docs`, `/openapi.json`, and `/health` endpoints remain public so that monitoring and discovery tools can reach them without credentials. Apply the `verify_api_key` dependency from `app/security.py` to any additional routers that should require the API key.

### Using plain Docker

If you prefer not to use Docker Compose:

```bash
docker build -t mfb-forecasting-api .
docker run --rm -p 8000:8000 mfb-forecasting-api
```

## Local Development (Optional)

If you still want to run the app directly on your host machine:

1. Create and activate a virtual environment (Python 3.11+ recommended).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the application:
   ```bash
   uvicorn app.main:app --reload
   ```

## Health Check

The `/health` endpoint returns a simple heartbeat payload that can be used for uptime monitoring.

## Data Quality Endpoints

User story 3 introduces a control layer so forecasters can mark anomalous months and keep them out of model training. The FastAPI service exposes the following routes under the `/api/data-quality` prefix (all secured by the `X-API-Key` header when configured):

- `POST /api/data-quality/flags` – create or update a manual month flag. Provide `month_key`, optional `agency_internal_id`/`item_id`, a `flag_type`, and a human-readable reason. When an automated flag already exists for the same scope, the system keeps its reason while activating the manual override.
- `GET /api/data-quality/flags` – list active flags with optional filters for month, agency, and item. Pass `include_inactive=true` to review historical records.
- `POST /api/data-quality/flags/deactivate` – deactivate a flag when the period is ready to return to training.
- `GET /api/data-quality/candidates` – retrieve anomaly candidates detected by the nightly build so that analysts can confirm them.

All endpoints read and write the Neon tables created by the migration CLI (`analytics.month_quality_flag`, `analytics.system_anomaly_candidates`, and related core tables). Ensure the CLI has run through `build-analytics` so those tables are populated before issuing API requests.

### Example workflow

1. **Start the API with database access**

   ```bash
   export API_KEY=change-me
   export DATABASE_URL="postgresql://neondb_owner:secret@your-host/neondb?sslmode=require&channel_binding=require"
   uv run uvicorn app.main:app --reload
   ```

2. **Create a manual flag**

   ```bash
   curl -X POST http://127.0.0.1:8000/api/data-quality/flags \
     -H "Content-Type: application/json" \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "month_key": "2023-03",
       "agency_internal_id": "A-100",
       "item_id": "P-352101",
       "flag_type": "ANOMALY",
       "flag_reason": "Manual anomaly test for March 2023",
       "expires_at_utc": "2025-11-02T13:15:32.706Z"
     }'
   ```

3. **Inspect flags**

   ```bash
   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/data-quality/flags?month_key=2023-03"
   ```

   Add `&include_inactive=true` to see previously deactivated rows.

4. **Deactivate the flag** (replace `FLAG_ID` with the value returned above)

   ```bash
   curl -X POST http://127.0.0.1:8000/api/data-quality/flags/deactivate \
     -H "Content-Type: application/json" \
     -H "X-API-Key: $API_KEY" \
     -d '{"flag_id": "FLAG_ID"}'
   ```

5. **Review system anomaly candidates**
   ```bash
   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/data-quality/candidates?month_key=2023-03"
   ```

These calls complete the manual override loop and verify that the Neon-backed control tables are wired correctly.

## Backtest Endpoints

User story 4 adds visibility into rolling-origin cross-validation performance against a seasonal naïve benchmark. The API exposes the following secured routes under the `/api/backtest` prefix:

- `POST /api/backtest/run` – enqueue a new backtest run for the requested horizons (defaults to H=1..4 with step size 1). Returns the `run_id` along with queue counts when the database procedure `core.enqueue_backtest_run` is installed.
- `GET /api/backtest/summary` – retrieve overall metrics (MAPE, RMSE, guardrail percentages) for the latest or specified run. Filter by horizon with the `h` query parameter.
- `GET /api/backtest/items` – paginate per-item metrics including champion model, MAPE/RMSE, and whether the item beat the seasonal naïve baseline. Supports filters for horizon, benchmark beat, model name, and item ID.
- `GET /api/backtest/items/{item_id}` – return detailed metrics for an item, including per-horizon summaries and the underlying window-level error series from `core.backtest_window_errors`.
- `GET /api/backtest/benchmark/method` – describe the seasonal naïve benchmark (periodicity 12) used for comparisons.

All backtest endpoints require the database pipeline to populate the `core.backtest_window_errors`, `analytics.backtest_item_summary`, and `analytics.backtest_overall_summary` tables. The service automatically falls back to the most recent run when `run_id` is omitted. In `ENVIRONMENT=local` / `dev` mode, `POST /api/backtest/run` returns a synthetic `run_id` when the stored procedure is missing so you can test the API contract before wiring the full pipeline.

### Purpose and production usage

- **Why these endpoints exist**: they publish rolling-origin cross-validation metrics so product teams can monitor whether ETS, Croston-SBA, or TSB champions outperform the seasonal naïve benchmark at horizons 1–4. The Performance dashboards and guardrail checks consume these metrics.
- **Production flow**: your backtest orchestration (StatsForecast job, dbt model, Airflow DAG, etc.) should enqueue a run (direct SQL or `POST /api/backtest/run`), compute window-level errors, and write results into the three tables above. The read endpoints then expose the latest run to the UI/API clients.
- **Cadence**: run the backtest pipeline weekly or on demand before major model changes. Forecast generation can remain nightly; backtests are heavier and meant for tactical validation.
- **Security**: grant the API role EXECUTE on `core.enqueue_backtest_run` and SELECT on the analytics tables in production. Restrict write access to the orchestration pipeline to avoid tampering with historical runs.

### Example workflow

1. **Trigger a backtest run** for horizons 1–4 (requires the `core.enqueue_backtest_run` stored procedure):

   ```bash
   curl -X POST "http://127.0.0.1:8000/api/backtest/run?h=1&h=2&h=3&h=4" \
     -H "X-API-Key: $API_KEY"
   ```

   Optional parameters:

   - `step_size` (default `1`) – slide the forecast origin by this many months per window.
   - `n_windows` – cap how many windows are generated; omit to let the database choose.

2. **Inspect overall metrics** for the latest run:

   ```bash
   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/backtest/summary?h=1&h=2"
   ```

3. **Review item-level performance** and filter to champions that beat the benchmark:

   ```bash
   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/backtest/items?h=1&beats_benchmark=true&page_size=25"
   ```

4. **Drill into a single item** (replace `ITEM_ID` with a real identifier) to view per-window errors:

   ```bash
   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/backtest/items/ITEM_ID?h=1&h=2"
   ```

## Forecasting Endpoints (User Story 5)

User story 5 introduces a per-item model champion pipeline that evaluates intermittent demand against ETS, Croston-SBA, and TSB. The service automatically routes each series to the right method and exposes the end-to-end workflow under the `/api/forecast` prefix. Everything is protected by the `X-API-Key` header (see [Configure security](#configure-security)).

### Data prerequisites

1. `core.item_month_demand` must contain one row per item-month with zero-filled gaps. The champion selector reads only from this table.
2. `analytics.item_classification`, `analytics.backtest_metrics`, `analytics.item_champion`, `analytics.forecast_item_month`, and `analytics.forecast_run` are populated by the API itself. The `migration/sql/local_forecast_stub.sql` script creates them for development environments.
3. The Docker image already installs everything in `requirements.txt`, including StatsForecast, pandas, numpy, and scipy.

To migrate the real warehouse data into the API schema, run (adjust the source view to match your environment):

```bash
psql "$DATABASE_URL" <<'SQL'
TRUNCATE core.item_month_demand;

INSERT INTO core.item_month_demand (item_id, period_start_date, demand)
SELECT item_id,
       month_start::date AS period_start_date,
       demand
FROM analytics.item_month_demand;
SQL
```

Confirm coverage before proceeding:

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*), MIN(period_start_date), MAX(period_start_date) FROM core.item_month_demand";
```

### Automatic pipeline triggers

- Set `PIPELINE_AUTO_RUN=true` (plus the optional interval and delay variables) to have the API run the full pipeline on a schedule after startup.
- Leave `PIPELINE_RUN_ON_DEMAND=true` (the default) when you want the service to kick off the pipeline automatically the first time a plan/forecast endpoint is hit and no runs exist yet. The request will block until the run completes so the UI immediately sees fresh results.
- Disable on-demand runs (`PIPELINE_RUN_ON_DEMAND=false`) if an external orchestrator handles all pipeline execution and you prefer the API to return 404s when no runs are found.

### Endpoints overview

| Method | Path                                            | Purpose                                                                                                                                                                                         |
| ------ | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST` | `/api/forecast/prep/build-item-month`           | Compute ADI/CV² for every SKU, classify demand (smooth/erratic/intermittent/lumpy), and flag obsolescence gates so TSB is only considered when the probability of demand is decaying.           |
| `POST` | `/api/forecast/train-select?h=1..4&step_size=1` | Run rolling-origin cross-validation with StatsForecast (`ETS`, `CrostonSBA`, `TSB`) alongside the seasonal naïve guardrail. Persists per-item, per-horizon metrics and the champion selections. |
| `POST` | `/api/forecast/forecast?h=1..4&run_id=<uuid>`   | Fit the chosen champion model(s) on the full history, write p50 plus conformal p10/p90 bands to `analytics.forecast_item_month`, and update run metadata.                                       |
| `GET`  | `/api/forecast/forecasts/items/{item_id}`       | Retrieve the champion summary and time-series forecast (p50/p10/p90) for a specific SKU. Filters horizons via repeated `h` query parameters.                                                    |
| `GET`  | `/api/forecast/plan?h=1`                        | Return the first-step plan for all items (next month, by default) including the champion method and p50/p10/p90 distribution for confidence bands.                                              |
| `GET`  | `/api/forecast/runs/latest`                     | Display the latest run metadata: horizons, counts of evaluated items, champions beating baseline, champion distribution, and timestamps.                                                        |

All responses use the real run id emitted by `train-select`; pass that id into `forecast`, `forecasts/items/{item_id}`, and `plan` when you want to interrogate a specific run.

### Typical workflow (real data)

1. **Prep** – compute demand classifications:

   ```bash
   curl -X POST http://127.0.0.1:8000/api/forecast/prep/build-item-month -H "X-API-Key: $API_KEY"
   ```

   Example response:

   ```json
   {
     "items_processed": 10,
     "intermittent_items": 10,
     "obsolescence_candidates": 10
   }
   ```

2. **Train & select champions** – multi-horizon rolling-origin CV (default `h=1..4`, `step_size=1`).

   ```bash
   curl -X POST "http://127.0.0.1:8000/api/forecast/train-select?h=1&h=2&h=3&h=4&step_size=1" \
     -H "X-API-Key: $API_KEY"
   ```

   Example response:

   ```json
   {
     "run_id": "a9a309aa-2b75-4f29-adbc-f4d57dae7fcc",
     "items_evaluated": 10,
     "items_with_champion": 10,
     "champion_counts": { "TSB": 40 }
   }
   ```

3. **Generate forecasts** – fit the selected champions and create p50 plus 80% conformal p10/p90 bands per horizon.

   ```bash
   curl -X POST "http://127.0.0.1:8000/api/forecast/forecast?h=1&h=2&h=3&h=4&run_id=a9a309aa-2b75-4f29-adbc-f4d57dae7fcc" \
     -H "X-API-Key: $API_KEY"
   ```

   Example response:

```json
{
  "items_forecasted": 10,
  "forecast_rows": 40,
  "forecast_months": 4
}
```

The TSB model now receives a conformal interval helper under the hood so that the API writes non-null bands even for intermittent or obsolescent series. Expect wide lower bounds (potentially negative) when historical demand is sparse; clamp in the UI if you prefer to display floor values at zero.

4. **Consume results** – tap into the read endpoints with the same run id:

   ```bash
   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/forecast/forecasts/items/P-352101?h=1&h=2&run_id=a9a309aa-2b75-4f29-adbc-f4d57dae7fcc"

   curl -H "X-API-Key: $API_KEY" \
     "http://127.0.0.1:8000/api/forecast/plan?h=1&run_id=a9a309aa-2b75-4f29-adbc-f4d57dae7fcc"

   curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/forecast/runs/latest
   ```

   Example `/api/forecast/plan` response:

   ```json
   {
     "run_id": "a9a309aa-2b75-4f29-adbc-f4d57dae7fcc",
     "horizon": 1,
     "items": [
       {
         "item_id": "P-352101",
         "period_start_date": "2026-12-01",
         "method": "TSB",
         "p50": 235.86,
         "p10": -394.78,
         "p90": 866.5
       }
       // …other items ...
     ]
   }
   ```

  Use the p10/p90 spread to draw planning bands in the UI; clamp or relabel negative values where business rules require non-negative quantities.

### Stubbed backtest helper (local only)

When you rely on the development scaffold (`migration/sql/local_backtest_stub.sql`), the `/api/backtest/run` endpoint enqueues jobs but does not compute accuracy metrics automatically. A helper script is available to populate placeholder values so the UI can display MAPE and benchmark columns during local development:

```bash
docker compose exec web python -m scripts.process_backtest_stub --run-id <run_id>
```

Omit `--run-id` to process the latest pending run. The script writes deterministic sample metrics and marks the queue entries complete. Replace it with your production backtest pipeline in shared or production environments.

### Database artifacts written by US-5

| Table                           | Purpose                                                                                               |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `analytics.item_classification` | ADI, CV², demand class, and obsolescence flag for every item processed by the prep endpoint.          |
| `analytics.backtest_metrics`    | Cross-validation metrics (MAPE, RMSE, fold counts) per item/horizon/method plus baseline comparisons. |
| `analytics.item_champion`       | Champion method per item/horizon, including guardrail signal (`beats_baseline` / `needs_review`).     |
| `analytics.forecast_run`        | Status tracker for each run (horizons, counts, champion distribution, timestamps).                    |
| `analytics.forecast_item_month` | Forecast outputs (p50, p10, p90) per item/horizon/period with the champion method.                    |

### Troubleshooting guide

| Symptom                                                      | Likely cause                                           | Remedy                                                                                                                              |
| ------------------------------------------------------------ | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `503` from prep endpoint                                     | `core.item_month_demand` missing or empty              | Load your harmonised demand data, or run the dev stub (`migration/sql/local_forecast_stub.sql`).                                    |
| `500` from train-select with `KeyError: 'model'`             | StatsForecast 1.x returns wide `cross_validation` data | The service flattens the frame automatically; ensure you are on the latest container build.                                         |
| `500` from forecast complaining about `prediction_intervals` | Old build still requesting level bands                 | Pull latest code and rebuild (`docker compose up --build`); the updated service wires TSB with conformal intervals for p10/p90.     |
| Champions always TSB                                         | Demand is heavily intermittent/obsolescing             | Validate `core.item_month_demand` and guardrail metrics; adjust obsolescence thresholds in `app/services/forecasting.py` if needed. |

### Why these models?

- **ETS** handles smooth demand and is the canonical exponential smoothing family for continuous series (Hyndman & Athanasopoulos, _Forecasting: Principles and Practice_).
- **Croston-SBA** is the bias-adjusted Croston variant recommended for intermittent demand (Nixtla StatsForecast docs).
- **TSB (Teunter-Syntetos-Babai)** updates demand probability each period, providing natural decay for obsolescence.
- All models come from [StatsForecast](https://nixtlaverse.nixtla.io/statsforecast/index.html); the API runs rolling-origin CV against a seasonal naïve benchmark and only promotes a champion when it beats that guardrail.

### End-to-end verification checklist

1. Load real demand into `core.item_month_demand`.
2. Run prep → train-select → forecast.
3. Confirm `analytics.item_classification`, `analytics.item_champion`, and `analytics.forecast_item_month` received rows.
4. Query `/api/forecast/runs/latest` and ensure `status` is `FORECASTED` with non-zero `items_with_champion` and `items_forecasted`.
5. Drill into `/api/forecast/forecasts/items/{item_id}` for a high-volume SKU and check that the champion method and p50 forecast align with business expectations.

Following these steps reproduces the observed verification run (`run_id=a9a309aa-2b75-4f29-adbc-f4d57dae7fcc`) that processed 10 real items from Neon, selected TSB champions where obsolescence signals were present, and generated four-month ahead projections.

### Local backtest queue (dev stub)

When you need the enqueue endpoint to return real queue counts without the production pipeline, apply the dev scaffold and run a smoke test:

1. Load the stub schema into your dev database (Neon or local Postgres):

   ```bash
   psql "$DATABASE_URL" -f migration/sql/local_backtest_stub.sql
   ```

   This creates queue tables plus a stubbed `core.enqueue_backtest_run` that inserts placeholder items (`ITEM-1`..`ITEM-3`). Edit the SQL to select from `analytics.item_month_demand` for richer tests and re-run the script if needed.

2. Start the API (`docker compose up --build` or `uvicorn app.main:app --reload`) and trigger a backtest run:

   ```bash
   curl -X POST "http://127.0.0.1:8000/api/backtest/run?h=1&h=2&h=3&h=4&step_size=1" \
     -H "X-API-Key: $API_KEY"
   ```

   Expect HTTP 202 with `items_enqueued` equal to the number of placeholder items multiplied by the number of horizons.

3. Populate results manually or via a lightweight worker so the read endpoints return data. Example worker logic is documented in the project history; at minimum insert rows into `core.backtest_window_errors`, `analytics.backtest_item_summary`, and `analytics.backtest_overall_summary` using the returned `run_id`.

4. Query the summaries to validate the flow:

   ```bash
   curl -H "X-API-Key: $API_KEY" "http://127.0.0.1:8000/api/backtest/summary?run_id=<run_id>"
   ```

### Backtest FAQ

- **Which horizons are evaluated by default?** `POST /api/backtest/run` defaults to horizons 1–4 months ahead. Provide one or more `h` query parameters to override (e.g., `?h=6&h=12`).
- **What happens if the database objects are missing?** The API returns HTTP 503 with guidance to install `core.enqueue_backtest_run` and the `core/analytics` backtest tables.
- **How is MAPE handled when demand is zero?** The pipeline populating the tables skips zero-actual windows in the denominator counts. API summaries surface both MAPE and RMSE so zero-demand SKUs remain comparable.
- **Can I request a specific run?** Pass `run_id=<uuid>` to any summary endpoint. Omitting it selects the most recent backtest automatically.
- **How do I sort item results?** Use `order_by` (`mape`, `rmse`, `item_id`, `model_name`, or `beats_benchmark`) with `descending=true` if you want highest-to-lowest ordering.
- **I want a real queue locally—how do I get it?** Apply `migration/sql/local_backtest_stub.sql` to your dev database. It creates queue tables and a stubbed `core.enqueue_backtest_run` that enqueues placeholder jobs so the API returns real counts. Replace the placeholder item list with a query against your demand table for richer tests.
