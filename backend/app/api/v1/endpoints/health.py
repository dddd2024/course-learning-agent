"""Health check endpoint."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Liveness probe. Returns ``{"status": "ok"}`` when the service is up."""
    return {"status": "ok"}
