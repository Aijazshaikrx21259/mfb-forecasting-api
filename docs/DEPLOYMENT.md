# Deployment Guide

## Render Deployment

### Prerequisites
- GitHub repository
- Render account
- Neon Postgres database

### Steps

1. **Push code to GitHub**
```bash
git push origin main
```

2. **Create Render service**
- Go to https://dashboard.render.com/
- Click "New +" → "Blueprint"
- Connect your GitHub repository
- Render will auto-detect `render.yaml`

3. **Configure environment variables**
Set these in Render dashboard:
- `ENVIRONMENT=production`
- `API_KEY=<your-secret-key>`
- `ALLOWED_ORIGINS=https://your-frontend.vercel.app`
- `DATABASE_URL=<neon-connection-string>`
- `PIPELINE_AUTO_RUN=false` (or true for scheduled runs)

4. **Deploy**
- Click "Apply" to deploy
- Wait for build to complete
- Service will be available at `https://your-app.onrender.com`

## Docker Deployment

### Local Docker
```bash
docker build -t mfb-forecasting-api .
docker run -p 8000:8000 \
  -e API_KEY=change-me \
  -e DATABASE_URL=postgresql://... \
  mfb-forecasting-api
```

### Docker Compose
```bash
docker compose up --build
```

## Environment Variables

### Required
- `API_KEY` - API authentication key
- `DATABASE_URL` - PostgreSQL connection string

### Optional
- `ENVIRONMENT` - `local`, `dev`, or `production`
- `ALLOWED_ORIGINS` - CORS allowed origins (required in production)
- `PIPELINE_AUTO_RUN` - Enable automatic pipeline runs
- `PIPELINE_INTERVAL_MINUTES` - Pipeline run interval

## Database Setup

1. **Create Neon database**
- Sign up at https://neon.tech
- Create new project
- Copy connection string

2. **Run migrations**
```bash
psql $DATABASE_URL -f migration/sql/alerts_schema.sql
psql $DATABASE_URL -f migration/sql/forecast_adjustments_schema.sql
```

## Health Checks

- Endpoint: `/health`
- Expected response: `{"status": "ok"}`
- Use for monitoring and uptime checks

## Monitoring

- Check `/api/metrics/system` for performance metrics
- Monitor logs in Render dashboard
- Set up alerts for errors

## Scaling

- Render free tier: 1 instance, 512MB RAM
- Upgrade to paid tier for:
  - Multiple instances
  - More memory
  - Custom domains
  - Better performance

## Troubleshooting

### Service won't start
- Check environment variables are set
- Verify DATABASE_URL is correct
- Check logs for errors

### Slow performance
- Check database connection pool size
- Monitor query performance
- Consider caching layer

### CORS errors
- Verify ALLOWED_ORIGINS includes your frontend URL
- Check ENVIRONMENT is set correctly
