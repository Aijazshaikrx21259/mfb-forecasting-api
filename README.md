# MFB Forecasting API

FastAPI service that exposes forecasting capabilities. The project currently provides a basic health endpoint and is structured to scale with additional routers and domain logic.

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

Endpoints and API documentation require an `X-API-Key` header when an API key is configured. Copy the sample environment file and adjust values to match your trusted clients (for example, your Vercel frontend and localhost):

```bash
cp env.example .env
# edit .env to set API_KEY, ALLOWED_ORIGINS, and DATABASE_URL
```

Then export those variables before launching or let Docker Compose read them automatically. When you deploy to production, set `ENVIRONMENT=production` so that requests are only accepted from the `ALLOWED_ORIGINS` allowlist.

```bash
API_KEY=super-secret \
ALLOWED_ORIGINS="https://my-frontend.vercel.app" \
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
