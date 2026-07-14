from types import SimpleNamespace

import pytest

from app.core.e2e_guard import validate_e2e_runtime


def _settings(tmp_path, *, upload=None, database=None, run_id="run-123"):
    run_root = tmp_path / "storage" / "e2e-runs" / run_id
    upload_dir = upload or (run_root / "uploads")
    database_path = database or (run_root / "e2e.db")
    return SimpleNamespace(
        ENVIRONMENT="e2e",
        E2E_RUN_ID=run_id,
        E2E_RUN_ROOT=str(run_root),
        UPLOAD_DIR=str(upload_dir),
        DATABASE_URL=f"sqlite:///{str(database_path).replace('\\', '/')}",
    )


def test_e2e_guard_accepts_paths_inside_unique_run_root(tmp_path):
    validate_e2e_runtime(_settings(tmp_path))


def test_e2e_guard_rejects_database_outside_run_root(tmp_path):
    settings = _settings(tmp_path, database=tmp_path / "course_assistant.db")
    with pytest.raises(RuntimeError, match="database must be inside"):
        validate_e2e_runtime(settings)


def test_e2e_guard_rejects_uploads_outside_run_root(tmp_path):
    settings = _settings(tmp_path, upload=tmp_path / "storage" / "uploads")
    with pytest.raises(RuntimeError, match="UPLOAD_DIR must be inside"):
        validate_e2e_runtime(settings)


def test_e2e_guard_requires_run_identity(tmp_path):
    settings = _settings(tmp_path)
    settings.E2E_RUN_ID = ""
    with pytest.raises(RuntimeError, match="E2E_RUN_ID"):
        validate_e2e_runtime(settings)


def test_non_e2e_environment_is_unchanged(tmp_path):
    settings = _settings(tmp_path)
    settings.ENVIRONMENT = "development"
    settings.UPLOAD_DIR = str(tmp_path / "storage" / "uploads")
    settings.DATABASE_URL = "sqlite:///./course_assistant.db"
    validate_e2e_runtime(settings)
