"""Migration tests isolated from the application's default SQLite database."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base, Course, Material, User

_MIGRATE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "migrate.py"


def _load_migrate_module():
    """Load migrate.py without leaking its import-time chdir to the test process."""
    previous_cwd = Path.cwd()
    try:
        spec = importlib.util.spec_from_file_location("migrate_script", _MIGRATE_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(previous_cwd)


@pytest.fixture()
def legacy_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-v3.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="migration_user", email="migration@example.com", password_hash="x")
    session.add(user); session.flush()
    course = Course(name="迁移测试课程", user_id=user.id)
    session.add(course); session.flush()
    material = Material(user_id=user.id, course_id=course.id, filename="legacy.txt", file_type="txt", file_path="legacy.txt", status="ready", version=1)
    session.add(material); session.commit()
    with engine.begin() as conn:
        conn.execute(text("UPDATE materials SET version = NULL WHERE id = :id"), {"id": material.id})
    session.close()
    try:
        yield engine
    finally:
        engine.dispose()


def _run_migration(monkeypatch, engine, *args: str) -> int:
    module = _load_migrate_module()
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(sys, "argv", ["migrate.py", *args])
    return module.main()


def test_dry_run_outputs_real_statistics(capsys, monkeypatch, legacy_database) -> None:
    assert _run_migration(monkeypatch, legacy_database, "--dry-run") == 0
    output = capsys.readouterr().out
    assert "materials_to_migrate" in output
    assert "would_change" in output


def test_migration_sets_version_for_historical_materials(monkeypatch, legacy_database) -> None:
    with legacy_database.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM materials WHERE version IS NULL")).scalar() == 1
    assert _run_migration(monkeypatch, legacy_database) == 0
    with legacy_database.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM materials WHERE version IS NULL OR version < 1")).scalar() == 0


def test_second_migration_run_reports_zero_changes(capsys, monkeypatch, legacy_database) -> None:
    assert _run_migration(monkeypatch, legacy_database) == 0
    capsys.readouterr()
    assert _run_migration(monkeypatch, legacy_database) == 0
    assert "changed=0" in capsys.readouterr().out
