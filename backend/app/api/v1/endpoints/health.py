"""Health check endpoint."""
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Liveness probe.

    Returns ``status``, ``app`` and ``version``. The ``app`` field is the
    project identifier (``course-learning-agent``) so the Windows launcher
    can verify port 8000 actually serves this backend before reusing it.
    """
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
