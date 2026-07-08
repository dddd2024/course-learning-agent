"""Health check endpoint."""
from fastapi import APIRouter

from app.core.config import app_build_info, settings

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Liveness probe.

    Returns ``status``, ``app``, ``version`` and ``build``. The ``app``
    field is the project identifier (``course-learning-agent``) so the
    Windows launcher can verify port 8000 actually serves this backend
    before reusing it.

    Task D: ``build`` exposes ``git_commit``, ``launch_id`` and
    ``started_at`` so ``start_windows.ps1`` can detect when port 8000 is
    held by a stale backend running an older commit and restart it
    instead of silently reusing it.
    """
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "build": app_build_info(),
    }
