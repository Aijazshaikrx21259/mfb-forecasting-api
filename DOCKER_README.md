# Docker Setup for MFB Forecasting API

This guide explains how to run the MFB Forecasting API using Docker.

## Prerequisites

- Docker installed on your system
- `.env` file configured with your database credentials

## Quick Start

### 1. Build the Docker image

```bash
cd mfb-forecasting-api
docker compose build
```

### 2. Run the container

```bash
docker compose up
```

Or run in detached mode (background):

```bash
docker compose up -d
```

### 3. Access the API

- **API Base URL:** http://localhost:8000
- **API Documentation:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/api/health

## Configuration

The API is configured via environment variables in `.env`:

```bash
# Required
DATABASE_URL=postgresql://user:password@host/dbname
API_KEY=your-secret-api-key

# Optional
ENVIRONMENT=local
ALLOWED_ORIGINS=http://localhost:3000
PIPELINE_AUTO_RUN=true
```

## What Happens on Startup

When the container starts, it will:

1. ✅ Wait for the database to be available (up to 2 minutes)
2. ✅ Apply forecast stub migrations (`local_forecast_stub.sql`)
3. ✅ Apply backtest stub migrations (`local_backtest_stub.sql`)
4. ✅ Populate sample backtest data for demo purposes
5. ✅ Start the FastAPI server on port 8000

## Common Commands

### View logs
```bash
docker compose logs -f
```

### Stop the container
```bash
docker compose down
```

### Restart the container
```bash
docker compose restart
```

### Rebuild and restart
```bash
docker compose up --build
```

### Execute commands inside the container
```bash
docker compose exec web bash
```

## Troubleshooting

### Database Connection Issues

If you see "Failed to connect to database" errors:

1. Check that `DATABASE_URL` is correctly set in `.env`
2. Ensure your database allows connections from Docker
3. For Neon/cloud databases, verify SSL settings

### Port Already in Use

If port 8000 is already in use:

```bash
# Find what's using the port
lsof -i :8000

# Kill the process or change the port in compose.yaml
```

### Reset Everything

To completely reset and rebuild:

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

## Testing the API

Once running, test with curl:

```bash
# Health check
curl http://localhost:8000/api/health

# Get forecast plan (requires API key)
curl -H "X-API-Key: change-me" \
  http://localhost:8000/api/forecast/plan?horizon=1

# Get backtest items
curl -H "X-API-Key: change-me" \
  http://localhost:8000/api/backtest/items?page_size=10
```

## Development vs Production

### Development (default)
- CORS allows `http://localhost:3000`
- Stub migrations auto-apply
- Sample data auto-populates

### Production
Set `ENVIRONMENT=production` and configure:
- `ALLOWED_ORIGINS` with your production frontend URL
- Strong `API_KEY`
- Production-grade `DATABASE_URL`

