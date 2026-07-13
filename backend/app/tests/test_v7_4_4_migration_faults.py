"""V7.4.4-02 fault-injection tests for migration 018's real SQLite path."""
from __future__ import annotations

import importlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


migration = importlib.import_module("app.db.versioned_migrations.018_v7_4_page_unique")


def make_legacy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE courses (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id))"))
        conn.execute(text("CREATE TABLE materials (id INTEGER PRIMARY KEY, course_id INTEGER REFERENCES courses(id))"))
        conn.execute(text("CREATE TABLE material_versions (id INTEGER PRIMARY KEY, material_id INTEGER REFERENCES materials(id))"))
        conn.execute(text("""
            CREATE TABLE material_pages (
                id INTEGER PRIMARY KEY,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                material_version_id INTEGER REFERENCES material_versions(id),
                page_no INTEGER NOT NULL,
                page_type TEXT NOT NULL DEFAULT 'text',
                parser_version TEXT NOT NULL DEFAULT 'legacy',
                raw_text TEXT, clean_text TEXT, blocks_json TEXT, decisions_json TEXT,
                created_at DATETIME, updated_at DATETIME
            )
        """))
        conn.execute(text("CREATE INDEX custom_pages_raw ON material_pages(raw_text)"))
        conn.execute(text("CREATE TRIGGER custom_pages_touch AFTER INSERT ON material_pages BEGIN SELECT 1; END"))
        conn.execute(text("INSERT INTO users VALUES (1)"))
        conn.execute(text("INSERT INTO courses VALUES (1, 1)"))
        conn.execute(text("INSERT INTO materials VALUES (1, 1)"))
        conn.execute(text("INSERT INTO material_versions VALUES (1, 1)"))
        conn.execute(text("""
            INSERT INTO material_pages VALUES
            (1, 1, 1, 1, 'text', 'v1', '中文', '', '[\"甲\"]', '{\"a\": null}', '2025-01-01', '2025-01-01'),
            (2, 1, NULL, 2, 'image', 'v1', '', 'Unicode Ω', '[]', '{}', '2025-01-02', '2025-01-02')
        """))
    return engine


def schema_snapshot(engine):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, type, sql FROM sqlite_master WHERE tbl_name='material_pages' AND type IN ('index', 'trigger') ORDER BY name")).fetchall()
        return {
            "hash": migration._compute_snapshot(conn),
            "rows": conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar_one(),
            "ddl": rows,
            "temp_exists": conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_pages_new'")).scalar() is not None,
        }


@pytest.mark.parametrize("stage", [
    "copy", "drop", "rename", "restore_ddl", "foreign_key_check", "snapshot_final",
])
def test_critical_stage_failure_rolls_back_everything(tmp_path, monkeypatch, stage):
    engine = make_legacy_engine(tmp_path)
    before = schema_snapshot(engine)

    def fail_at_stage(actual_stage, conn):
        if actual_stage == stage:
            raise RuntimeError(f"injected failure: {stage}")

    monkeypatch.setattr(migration, "_run_stage", fail_at_stage)
    with pytest.raises(RuntimeError, match=f"injected failure: {stage}"):
        migration.up(Session(engine), engine)

    after = schema_snapshot(engine)
    assert after == before
    assert not migration._has_unique_constraint(engine)


def test_success_preserves_hash_custom_ddl_and_is_idempotent(tmp_path):
    engine = make_legacy_engine(tmp_path)
    before = schema_snapshot(engine)

    migration.up(Session(engine), engine)
    after = schema_snapshot(engine)

    assert after["hash"] == before["hash"]
    assert after["rows"] == before["rows"]
    assert {row[0] for row in after["ddl"]} >= {"custom_pages_raw", "custom_pages_touch"}
    assert not after["temp_exists"]
    assert migration._has_unique_constraint(engine)

    migration.up(Session(engine), engine)
    assert schema_snapshot(engine)["hash"] == before["hash"]


def test_existing_temp_table_fails_closed_without_overwrite(tmp_path):
    engine = make_legacy_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE material_pages_new (id INTEGER)"))

    with pytest.raises(RuntimeError, match="material_pages_new"):
        migration.up(Session(engine), engine)
    assert schema_snapshot(engine)["temp_exists"]
