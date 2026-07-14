"""Health check endpoint."""
import os
import signal
from threading import Timer

from fastapi import APIRouter, HTTPException

from app.core.config import app_build_info, e2e_runtime_info, settings

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
        "e2e": e2e_runtime_info(),
    }


@router.post("/e2e/shutdown")
def e2e_shutdown() -> dict:
    """Stop an isolated test server after its browser suite has finished."""
    if not settings.E2E_MODE:
        raise HTTPException(status_code=404, detail="not an E2E server")
    Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"status": "stopping", "run_id": settings.E2E_RUN_ID}
