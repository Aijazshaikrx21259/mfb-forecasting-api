# MFB Forecasting API

FastAPI service that exposes forecasting capabilities. The project currently provides a basic health endpoint and is structured to scale with additional routers and domain logic.

## Quick Start (Docker)

The project ships with a `Dockerfile` and `compose.yaml` so you can run it on macOS, Windows, or Linux without installing Python.

1. Build and start the service (first run may take a minute while the image is built):
   ```bash
   docker compose up --build
   ```
2. Visit the interactive Swagger UI at `http://127.0.0.1:8000/docs` (the root URL redirects there automatically) or call the health check at `http://127.0.0.1:8000/health`.

To stop the containers press `Ctrl+C` and optionally remove them with `docker compose down`.

### Configure security

Endpoints and API documentation require an `X-API-Key` header when an API key is configured. Copy the sample environment file and adjust values to match your trusted clients (for example, your Vercel frontend and localhost):

```bash
cp env.example .env
# edit .env to set API_KEY and ALLOWED_ORIGINS
```

Then export those variables before launching or let Docker Compose read them automatically. When you deploy to production, set `ENVIRONMENT=production` so that requests are only accepted from the `ALLOWED_ORIGINS` allowlist.

```bash
API_KEY=super-secret \
ALLOWED_ORIGINS="https://my-frontend.vercel.app" \
ENVIRONMENT=production \
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
