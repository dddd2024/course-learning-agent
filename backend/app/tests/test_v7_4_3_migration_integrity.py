"""V7.4.3-02 checks for transactional metadata preservation."""
from __future__ import annotations
import importlib
from sqlalchemy import create_engine, text

migration = importlib.import_module("app.db.versioned_migrations.018_v7_4_page_unique")


def test_exact_unique_detection_does_not_use_sql_text_heuristics(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unique.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE material_pages (id INTEGER PRIMARY KEY, material_version_id INTEGER, page_no INTEGER)"))
        conn.execute(text("CREATE UNIQUE INDEX wrong_pair ON material_pages(page_no, material_version_id)"))
    assert not migration._has_unique_constraint(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX wrong_pair"))
        conn.execute(text("CREATE UNIQUE INDEX exact_pair ON material_pages(material_version_id, page_no)"))
    assert migration._has_unique_constraint(engine)


def test_snapshot_uses_same_connection_and_custom_ddl_is_collected(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ddl.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE material_pages (id INTEGER PRIMARY KEY, material_id INTEGER, material_version_id INTEGER, page_no INTEGER, page_type TEXT, parser_version TEXT, raw_text TEXT, clean_text TEXT, blocks_json TEXT, decisions_json TEXT, created_at TEXT, updated_at TEXT)"))
        conn.execute(text("CREATE INDEX custom_pages_raw ON material_pages(raw_text)"))
        conn.execute(text("CREATE TRIGGER custom_pages_touch AFTER INSERT ON material_pages BEGIN SELECT 1; END"))
        conn.execute(text("INSERT INTO material_pages VALUES (1, 1, 1, 1, 'text', 'v', '中文', '', '[]', '[]', 't', 't')"))
        before = migration._compute_snapshot(conn)
        assert before == migration._compute_snapshot(conn)
        ddl = migration._preserved_ddl(conn)
    assert any("custom_pages_raw" in item for item in ddl)
    assert any("custom_pages_touch" in item for item in ddl)
