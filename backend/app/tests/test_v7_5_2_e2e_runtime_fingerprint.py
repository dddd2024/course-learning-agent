"""Regression tests for API/worker E2E runtime identity fingerprints."""
from __future__ import annotations

from pathlib import Path

from app.core.config import _runtime_path_fingerprint, _sqlite_database_path


def test_sqlite_runtime_fingerprint_is_independent_of_process_working_directory(
    tmp_path: Path, monkeypatch,
) -> None:
    run_root = tmp_path / "course-learning-agent-e2e" / "ci-123-1"
    database = run_root / "e2e.db"
    database.parent.mkdir(parents=True)
    database_url = f"sqlite:///{database.as_posix()}"

    api_cwd = tmp_path / "api"
    worker_cwd = tmp_path / "worker"
    api_cwd.mkdir()
    worker_cwd.mkdir()

    monkeypatch.chdir(api_cwd)
    api_fingerprint = _runtime_path_fingerprint(_sqlite_database_path(database_url))

    monkeypatch.chdir(worker_cwd)
    worker_fingerprint = _runtime_path_fingerprint(_sqlite_database_path(database_url))

    assert _sqlite_database_path(database_url) == database.resolve()
    assert api_fingerprint == worker_fingerprint


def test_sqlite_runtime_path_supports_relative_development_urls(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert _sqlite_database_path("sqlite:///./e2e.db") == (tmp_path / "e2e.db").resolve()
