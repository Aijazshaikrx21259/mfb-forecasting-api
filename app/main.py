"""Entrypoint for the MFB Forecasting FastAPI application."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import get_settings
from app.db import close_db_pool, init_db_pool
from app.routers import adjustments, alert_preferences, alerts, backtest, data_quality, forecast, health, metrics
from app.services.pipeline_scheduler import ForecastPipelineScheduler

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Instantiate and configure the FastAPI application."""

    settings = get_settings()

    app = FastAPI(
        title="MFB Forecasting API",
        description="Service providing health monitoring and forecasting capabilities.",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    cors_kwargs: dict[str, object] = {
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }

    if settings.allow_all_origins:
        cors_kwargs.update(
            {
                "allow_origin_regex": ".*",
                "allow_credentials": False,
            }
        )
    else:
        cors_kwargs.update(
            {
                "allow_origins": settings.allowed_origins,
                "allow_credentials": True,
            }
    )

    app.add_middleware(CORSMiddleware, **cors_kwargs)

    pipeline_scheduler = ForecastPipelineScheduler(
        enabled=settings.pipeline_auto_run and bool(settings.database_url),
        interval_minutes=settings.pipeline_interval_minutes,
        initial_delay_seconds=settings.pipeline_initial_delay_seconds,
        stable_interval_minutes=settings.pipeline_stable_interval_minutes,
        volatile_interval_minutes=settings.pipeline_volatile_interval_minutes,
    )
    app.state.pipeline_scheduler = pipeline_scheduler

    app.include_router(health.router)
    app.include_router(alerts.router)
    app.include_router(alert_preferences.router)
    app.include_router(adjustments.router)
    app.include_router(backtest.router)
    app.include_router(data_quality.router)
    app.include_router(forecast.router)
    app.include_router(metrics.router)

    @app.on_event("startup")
    async def startup_event() -> None:
        """Initialise shared resources."""

        if not settings.database_url:
            logger.warning(
                "DATABASE_URL not configured; data-quality endpoints will raise 503 responses."
            )
        await init_db_pool(settings.database_url)
        await pipeline_scheduler.start()

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        """Release shared resources."""

        await pipeline_scheduler.stop()
        await close_db_pool()

    @app.get("/", include_in_schema=False)
    async def redirect_to_docs() -> RedirectResponse:
        """Redirect the root to the interactive documentation."""

        return RedirectResponse(url="/docs", status_code=307)

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_endpoint() -> JSONResponse:
        """Serve the OpenAPI schema."""

        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui():
        """Serve the Swagger UI interface."""

        return get_swagger_ui_html(
            openapi_url="/openapi.json", title=f"{app.title} - Docs"
        )

    return app


app = create_application()
