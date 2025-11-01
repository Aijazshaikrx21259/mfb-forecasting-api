"""Entrypoint for the MFB Forecasting FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import get_settings
from app.routers import health


def create_application() -> FastAPI:
    """Instantiate and configure the FastAPI application."""

    settings = get_settings()

    app = FastAPI(
        title="MFB Forecasting API",
        description="Service providing health monitoring and forecasting capabilities.",
        version="0.1.0",
        contact={
            "name": "Platform Engineering",
            "email": "platform@example.com",
        },
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    cors_kwargs: dict[str, object] = {
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }

    if settings.allow_all_origins:
        cors_kwargs.update({
            "allow_origin_regex": ".*",
            "allow_credentials": False,
        })
    else:
        cors_kwargs.update({
            "allow_origins": settings.allowed_origins,
            "allow_credentials": True,
        })

    app.add_middleware(CORSMiddleware, **cors_kwargs)

    app.include_router(health.router)

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

        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Docs")

    return app


app = create_application()


