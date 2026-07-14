"""Fail-fast validation for isolated Playwright/E2E processes."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url


def _is_relative_to(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_e2e_runtime(settings) -> None:
    """Reject E2E processes that point at normal or shared data paths.

    The guard is intentionally invoked before the SQLAlchemy engine is created,
    so an invalid Playwright environment cannot touch a development database.
    """
    if str(getattr(settings, "ENVIRONMENT", "")).lower() != "e2e":
        return

    run_id = str(getattr(settings, "E2E_RUN_ID", "") or "").strip()
    run_root_raw = str(getattr(settings, "E2E_RUN_ROOT", "") or "").strip()
    if not run_id or not run_root_raw:
        raise RuntimeError("E2E isolation requires E2E_RUN_ID and E2E_RUN_ROOT")

    run_root = Path(run_root_raw).expanduser().resolve()
    upload_dir = Path(str(settings.UPLOAD_DIR)).expanduser().resolve()
    if run_id not in run_root.parts:
        raise RuntimeError("E2E_RUN_ROOT must contain the current E2E_RUN_ID")
    if not _is_relative_to(upload_dir, run_root):
        raise RuntimeError("E2E UPLOAD_DIR must be inside E2E_RUN_ROOT")

    url = make_url(str(settings.DATABASE_URL))
    if not url.drivername.startswith("sqlite") or not url.database:
        raise RuntimeError("E2E DATABASE_URL must be an isolated SQLite database")
    database_path = Path(url.database).expanduser().resolve()
    if not _is_relative_to(database_path, run_root):
        raise RuntimeError("E2E database must be inside E2E_RUN_ROOT")

    normal_uploads = (Path(__file__).resolve().parents[3] / "storage" / "uploads").resolve()
    if upload_dir == normal_uploads or _is_relative_to(upload_dir, normal_uploads):
        raise RuntimeError("E2E UPLOAD_DIR must not point at normal storage/uploads")
