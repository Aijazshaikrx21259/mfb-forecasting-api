"""Entrypoint for the MFB Forecasting FastAPI application."""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.routers import health


def create_application() -> FastAPI:
    """Instantiate and configure the FastAPI application."""

    app = FastAPI(
        title="MFB Forecasting API",
        description="Service providing health monitoring and forecasting capabilities.",
        version="0.1.0",
        contact={
            "name": "Platform Engineering",
            "email": "platform@example.com",
        },
    )

    app.include_router(health.router)

    @app.get("/", include_in_schema=False)
    async def redirect_to_docs() -> RedirectResponse:
        """Redirect the root to the interactive documentation."""

        return RedirectResponse(url="/docs", status_code=307)

    return app


app = create_application()


