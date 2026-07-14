"""Existing-database AUTOINCREMENT upgrade regression."""
from __future__ import annotations

from sqlalchemy import create_engine, text

from app.db.versioned_migrations import __dict__ as migrations_package
from importlib import import_module


def test_material_autoincrement_rebuild_preserves_rows_and_advances_identity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE materials (id INTEGER PRIMARY KEY, filename VARCHAR(255) NOT NULL)"))
        conn.execute(text("INSERT INTO materials(id, filename) VALUES (5, 'old.pdf')"))
        conn.execute(text("DELETE FROM materials WHERE id=5"))
        conn.execute(text("INSERT INTO materials(id, filename) VALUES (4, 'retained.pdf')"))
    migration = import_module("app.db.versioned_migrations.024_v7_5_2_page_catalog_recovery")

    migration._rebuild_materials_for_autoincrement(engine)
    migration._rebuild_materials_for_autoincrement(engine)

    with engine.begin() as conn:
        sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='materials'")).scalar_one()
        conn.execute(text("INSERT INTO materials(filename) VALUES ('new.pdf')"))
        new_id = conn.execute(text("SELECT id FROM materials WHERE filename='new.pdf'" )).scalar_one()
        assert "AUTOINCREMENT" in sql.upper()
        assert new_id > 4
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
