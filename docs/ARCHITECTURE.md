# Architecture Overview

## System Design

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   UI (Next  │─────▶│  FastAPI     │─────▶│  Neon       │
│   .js)      │      │  Backend     │      │  Postgres   │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ StatsForecast│
                     │  (ETS, TSB,  │
                     │   Croston)    │
                     └──────────────┘
```

## Components

### API Layer (`app/routers/`)
- **alerts.py** - Alert CRUD operations
- **alert_preferences.py** - User alert settings
- **adjustments.py** - Forecast adjustments
- **backtest.py** - Model performance tracking
- **data_quality.py** - Data quality flags
- **forecast.py** - Forecasting pipeline
- **health.py** - Health checks
- **metrics.py** - System metrics

### Service Layer (`app/services/`)
- **alert_service.py** - Alert business logic
- **alert_triggers.py** - Event-based alert generation
- **adjustment_service.py** - Adjustment operations
- **forecasting.py** - Core forecasting logic
- **pipeline_scheduler.py** - Automated pipeline runs

### Models (`app/models/`)
- **alerts.py** - Alert Pydantic models
- **adjustments.py** - Adjustment Pydantic models

### Database
- **alerts schema** - User notifications
- **adjustments schema** - Forecast overrides
- **analytics schema** - Forecasting results
- **core schema** - Base data tables

## Data Flow

### Forecasting Pipeline
1. **Prep** - Classify demand patterns (ADI/CV²)
2. **Train** - Rolling-origin cross-validation
3. **Select** - Choose champion model per item
4. **Forecast** - Generate p50/p10/p90 predictions
5. **Alert** - Notify users of completion

### Alert System
1. **Trigger** - Event occurs (forecast ready, spike detected)
2. **Create** - Generate alert from template
3. **Notify** - Store in database for UI retrieval
4. **Read** - User views and acknowledges

### Adjustment Workflow
1. **Create** - User submits adjustment with reason
2. **Review** - Approve or reject
3. **Apply** - Supersede old adjustments
4. **Audit** - Track history of changes

## Security

- API key authentication on all endpoints
- CORS configuration per environment
- Input validation and sanitization
- SQL injection prevention (parameterized queries)

## Performance

- Async database connections (asyncpg)
- Connection pooling (1-10 connections)
- Metrics middleware for monitoring
- Efficient SQL queries with indexes

## Scalability

- Stateless API design
- Horizontal scaling ready
- Database connection pooling
- Background task scheduling
