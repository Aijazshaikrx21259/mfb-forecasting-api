"""Health check router for the API."""

from fastapi import APIRouter


router = APIRouter(tags=["health"], prefix="")


@router.get("/health", summary="Health check", response_description="Health status")
async def get_health_status() -> dict[str, str]:
    """Return a simple heartbeat payload for uptime checks."""

    return {"status": "ok"}


