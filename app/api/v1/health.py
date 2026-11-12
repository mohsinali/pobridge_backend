"""Application health endpoint."""

from fastapi import APIRouter, status

from app import __version__
from app.core.config import settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check application health",
)
def health_check() -> HealthResponse:
    """Return basic application health information."""
    return HealthResponse(
        status="ok",
        application=settings.APP_NAME,
        version=__version__,
    )
