"""V7.5.2-04 E2E runtime isolation contract tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings


def _isolated_settings(tmp_path: Path, run_id: str = "run-123") -> Settings:
    run_root = tmp_path / ".e2e-runs" / run_id
    database_url = f"sqlite:///{(run_root / 'e2e.db').as_posix()}"
    upload_dir = str(run_root / "uploads")
    parsed_dir = str(run_root / "parsed")
    return Settings(
        _env_file=None,
        E2E_MODE=True,
        E2E_RUN_ID=run_id,
        E2E_DATABASE_URL=database_url,
        DATABASE_URL=database_url,
        E2E_UPLOAD_DIR=upload_dir,
        UPLOAD_DIR=upload_dir,
        E2E_PARSED_DIR=parsed_dir,
        PARSED_DIR=parsed_dir,
    )


def test_non_e2e_runtime_keeps_normal_defaults() -> None:
    settings = Settings(_env_file=None, E2E_MODE=False)
    settings.validate_e2e_isolation()


def test_e2e_runtime_accepts_unique_run_root(tmp_path: Path) -> None:
    settings = _isolated_settings(tmp_path)
    settings.validate_e2e_isolation()


def test_e2e_runtime_requires_explicit_mirror_variables(tmp_path: Path) -> None:
    settings = _isolated_settings(tmp_path)
    settings.E2E_UPLOAD_DIR = ""

    with pytest.raises(ValueError, match="E2E_UPLOAD_DIR"):
        settings.validate_e2e_isolation()


def test_e2e_runtime_rejects_database_mismatch(tmp_path: Path) -> None:
    settings = _isolated_settings(tmp_path)
    settings.DATABASE_URL = "sqlite:///./course_assistant.db"

    with pytest.raises(ValueError, match="DATABASE_URL"):
        settings.validate_e2e_isolation()


def test_e2e_runtime_rejects_normal_storage_paths(tmp_path: Path) -> None:
    settings = _isolated_settings(tmp_path)
    normal_uploads = tmp_path / "storage" / "uploads"
    settings.UPLOAD_DIR = str(normal_uploads)
    settings.E2E_UPLOAD_DIR = str(normal_uploads)

    with pytest.raises(ValueError, match=".e2e-runs"):
        settings.validate_e2e_isolation()


def test_e2e_runtime_rejects_unsafe_run_id(tmp_path: Path) -> None:
    settings = _isolated_settings(tmp_path)
    settings.E2E_RUN_ID = "../escape"

    with pytest.raises(ValueError, match="safe"):
        settings.validate_e2e_isolation()
