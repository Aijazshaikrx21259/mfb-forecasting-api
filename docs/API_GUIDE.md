# API Guide

## Overview

The MFB Forecasting API provides endpoints for demand forecasting, data quality management, alerts, and forecast adjustments.

## Base URL

- **Local**: `http://localhost:8000`
- **Production**: `https://your-api-domain.com`

## Authentication

All endpoints (except `/health`, `/docs`, `/openapi.json`) require an API key in the header:

```
X-API-Key: your-api-key-here
```

## Core Endpoints

### Forecasting

- `POST /api/forecast/prep/build-item-month` - Prepare item classifications
- `POST /api/forecast/train-select` - Train models and select champions
- `POST /api/forecast/forecast` - Generate forecasts
- `GET /api/forecast/forecasts/items/{item_id}` - Get item forecast
- `GET /api/forecast/plan` - Get purchase plan
- `GET /api/forecast/runs/latest` - Get latest run metadata

### Alerts

- `POST /api/alerts` - Create alert
- `GET /api/alerts` - List alerts (with filters)
- `PATCH /api/alerts/{alert_id}` - Update alert status
- `POST /api/alerts/mark-all-read` - Mark all as read
- `GET /api/alert-preferences` - Get user preferences
- `PUT /api/alert-preferences` - Update preferences

### Adjustments

- `POST /api/adjustments` - Create forecast adjustment
- `GET /api/adjustments` - List adjustments (with filters)
- `PATCH /api/adjustments/{adjustment_id}` - Update adjustment
- `POST /api/adjustments/{adjustment_id}/review` - Approve/reject
- `GET /api/adjustments/{adjustment_id}/history` - View audit trail
- `GET /api/adjustments/templates/list` - List templates
- `POST /api/adjustments/templates/{template_id}/apply` - Apply template

### Backtest

- `POST /api/backtest/run` - Trigger backtest
- `GET /api/backtest/summary` - Get performance summary
- `GET /api/backtest/items` - List item performance
- `GET /api/backtest/items/{item_id}` - Get item details

### Data Quality

- `POST /api/data-quality/flags` - Create quality flag
- `GET /api/data-quality/flags` - List flags
- `POST /api/data-quality/flags/deactivate` - Deactivate flag
- `GET /api/data-quality/candidates` - Get anomaly candidates

### Metrics

- `GET /api/metrics/system` - System performance metrics
- `GET /api/metrics/costs` - Cost estimation

## Response Formats

All responses are JSON with standard structure:

### Success Response
```json
{
  "field1": "value1",
  "field2": "value2"
}
```

### Error Response
```json
{
  "detail": "Error message here"
}
```

## Status Codes

- `200` - Success
- `201` - Created
- `204` - No Content
- `400` - Bad Request
- `401` - Unauthorized
- `404` - Not Found
- `422` - Validation Error
- `500` - Server Error
- `503` - Service Unavailable

## Rate Limiting

No rate limiting currently implemented. Consider adding in production.

## Examples

### Create Alert
```bash
curl -X POST http://localhost:8000/api/alerts \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -d '{
    "user_id": "user123",
    "alert_type": "FORECAST_READY",
    "priority": "MEDIUM",
    "title": "New Forecast Available",
    "message": "Forecast completed successfully",
    "adjusted_by": "user123"
  }'
```

### Create Adjustment
```bash
curl -X POST http://localhost:8000/api/adjustments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -d '{
    "item_id": "P-352101",
    "run_id": "uuid-here",
    "horizon": 1,
    "period_start_date": "2024-01-01",
    "adjusted_p50": 150.0,
    "adjustment_reason": "Promotional event expected",
    "adjusted_by": "user123"
  }'
```

## Interactive Documentation

Visit `/docs` for interactive Swagger UI documentation.
