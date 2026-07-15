"""Regression coverage for a real pre-V7.5.2 SQLite material schema."""
from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import create_engine, text


def _legacy_engine(tmp_path, *, include_active_version_foreign_key: bool = True):
    """Build the historical shape used by deployed SQLAlchemy installations.

    In particular, ``id INTEGER NOT NULL, PRIMARY KEY (id)`` is intentionally
    *not* ``AUTOINCREMENT``.  The fixture includes the related tables and
    legacy page assets that a production migration actually needs to preserve.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-v752.db'}")
    active_version_foreign_key = (
        ", FOREIGN KEY(active_version_id) REFERENCES material_versions(id)"
        if include_active_version_foreign_key
        else ""
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL, password_hash VARCHAR(255) NOT NULL, email VARCHAR(100))"))
        conn.execute(text("CREATE TABLE courses (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, teacher VARCHAR(100), semester VARCHAR(50), description TEXT, color VARCHAR(20), FOREIGN KEY(user_id) REFERENCES users(id))"))
        conn.execute(text(f"""
            CREATE TABLE materials (
                id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                filename VARCHAR(255) NOT NULL,
                file_type VARCHAR(20) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                status VARCHAR(30), version INTEGER, active_version_id INTEGER,
                error_message TEXT, uploaded_at DATETIME, created_at DATETIME,
                updated_at DATETIME, parse_started_at DATETIME,
                parse_finished_at DATETIME, parse_attempts INTEGER NOT NULL DEFAULT 0,
                last_parse_error TEXT,
                PRIMARY KEY (id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(course_id) REFERENCES courses(id){active_version_foreign_key}
            )
        """))
        conn.execute(text("CREATE INDEX ix_materials_user_id ON materials(user_id)"))
        conn.execute(text("CREATE INDEX ix_materials_course_id ON materials(course_id)"))
        conn.execute(text("CREATE TABLE material_versions (id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL, version INTEGER NOT NULL, status VARCHAR(30) NOT NULL, content_hash VARCHAR(64), parsed_at DATETIME, created_at DATETIME, updated_at DATETIME, FOREIGN KEY(material_id) REFERENCES materials(id))"))
        conn.execute(text("CREATE TABLE material_pages (id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL, material_version_id INTEGER, page_no INTEGER NOT NULL, page_type VARCHAR(30) NOT NULL, parser_version VARCHAR(32) NOT NULL, raw_text TEXT, clean_text TEXT, blocks_json TEXT, decisions_json TEXT, created_at DATETIME, updated_at DATETIME, FOREIGN KEY(material_id) REFERENCES materials(id), FOREIGN KEY(material_version_id) REFERENCES material_versions(id))"))
        conn.execute(text("CREATE TABLE material_page_assets (id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL, material_version_id INTEGER NOT NULL, page_no INTEGER NOT NULL, asset_path VARCHAR(500), mime_type VARCHAR(64) NOT NULL, width INTEGER, height INTEGER, dpi INTEGER NOT NULL, sha256 VARCHAR(64), render_status VARCHAR(30) NOT NULL, error_code VARCHAR(100), created_at DATETIME, updated_at DATETIME, FOREIGN KEY(material_id) REFERENCES materials(id), FOREIGN KEY(material_version_id) REFERENCES material_versions(id))"))
        conn.execute(text("INSERT INTO users(id, username, password_hash) VALUES (1, 'legacy', 'hash')"))
        conn.execute(text("INSERT INTO courses(id, user_id, name) VALUES (1, 1, 'legacy course')"))
        conn.execute(text("INSERT INTO materials(id, user_id, course_id, filename, file_type, file_path, status, version, parse_attempts) VALUES (8, 1, 1, 'deleted-high.pdf', 'pdf', 'uploads/deleted.pdf', 'ready', 1, 0)"))
        conn.execute(text("DELETE FROM materials WHERE id=8"))
        conn.execute(text("INSERT INTO materials(id, user_id, course_id, filename, file_type, file_path, status, version, parse_attempts) VALUES (7, 1, 1, 'legacy.pdf', 'pdf', 'uploads/legacy.pdf', 'ready', 1, 0)"))
        conn.execute(text("INSERT INTO material_versions(id, material_id, version, status) VALUES (12, 7, 1, 'ready')"))
        conn.execute(text("UPDATE materials SET active_version_id=12 WHERE id=7"))
        conn.execute(text("INSERT INTO material_page_assets(id, material_id, material_version_id, page_no, mime_type, dpi, render_status) VALUES (20, 7, 12, 1, 'image/png', 144, 'ready'), (21, 7, 12, 2, 'image/png', 144, 'ready')"))
    return engine


def _migration():
    return import_module("app.db.versioned_migrations.024_v7_5_2_page_catalog_recovery")


def test_real_legacy_schema_migration_preserves_data_backfills_pages_and_is_idempotent(tmp_path):
    engine = _legacy_engine(tmp_path)
    migration = _migration()

    dry_run = migration.dry_run(None, engine)
    assert dry_run["material_autoincrement_missing"] is True
    assert dry_run["public_id_missing"] is True
    assert dry_run["missing_page_rows"] == 2

    migration.up(None, engine)
    first = migration.inspect_materials_schema(engine.connect())
    migration.up(None, engine)
    second = migration.inspect_materials_schema(engine.connect())

    assert first.schema_hash == second.schema_hash
    assert first.row_count == second.row_count == 1
    assert first.has_autoincrement is True
    assert first.has_public_id is True
    with engine.begin() as conn:
        material = conn.execute(text("SELECT id, public_id, filename FROM materials")).mappings().one()
        assert material["id"] == 7
        assert len(material["public_id"]) == 36
        assert conn.execute(text("SELECT COUNT(*) FROM material_pages WHERE material_id=7 AND material_version_id=12")).scalar_one() == 2
        # A deleted high watermark from before the migration cannot be
        # reconstructed.  AUTOINCREMENT must only promise non-reuse from now.
        conn.execute(text("INSERT INTO materials(user_id, course_id, filename, file_type, file_path, parse_attempts, public_id) VALUES (1, 1, 'post-migration.pdf', 'pdf', 'uploads/post.pdf', 0, '00000000-0000-4000-8000-000000000001')"))
        created_id = conn.execute(text("SELECT id FROM materials WHERE filename='post-migration.pdf'")).scalar_one()
        conn.execute(text("DELETE FROM materials WHERE id=:id"), {"id": created_id})
        conn.execute(text("INSERT INTO materials(user_id, course_id, filename, file_type, file_path, parse_attempts, public_id) VALUES (1, 1, 'post-migration-2.pdf', 'pdf', 'uploads/post2.pdf', 0, '00000000-0000-4000-8000-000000000002')"))
        assert conn.execute(text("SELECT id FROM materials WHERE filename='post-migration-2.pdf'")).scalar_one() > created_id
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_rebuild_failure_rolls_back_schema_rows_indexes_and_foreign_keys(tmp_path, monkeypatch):
    engine = _legacy_engine(tmp_path)
    migration = _migration()
    with engine.connect() as conn:
        before = migration.inspect_materials_schema(conn)

    def fail_after_swap(conn, snapshot):
        raise RuntimeError("injected index restore failure")

    monkeypatch.setattr(migration, "restore_material_indexes", fail_after_swap)
    with pytest.raises(RuntimeError, match="injected index restore failure"):
        migration._rebuild_materials_for_autoincrement(engine)

    with engine.connect() as conn:
        after = migration.inspect_materials_schema(conn)
        assert after.schema_hash == before.schema_hash
        assert after.row_count == before.row_count
        assert after.indexes == before.indexes
        assert after.foreign_keys == before.foreign_keys
        assert conn.execute(text("SELECT COUNT(*) FROM materials WHERE id=7")).scalar_one() == 1
        assert conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='materials__v752_new'")).scalar() is None
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_legacy_schema_without_active_version_foreign_key_is_upgraded(tmp_path):
    """Older deployed databases omitted the active-version constraint."""
    engine = _legacy_engine(tmp_path, include_active_version_foreign_key=False)
    migration = _migration()

    migration.up(None, engine)

    with engine.connect() as conn:
        foreign_keys = {tuple(row[2:]) for row in conn.execute(text("PRAGMA foreign_key_list(materials)")).fetchall()}
        assert ("users", "user_id", "id", "NO ACTION", "NO ACTION", "NONE") in foreign_keys
        assert ("courses", "course_id", "id", "NO ACTION", "NO ACTION", "NONE") in foreign_keys
        assert ("material_versions", "active_version_id", "id", "NO ACTION", "NO ACTION", "NONE") in foreign_keys
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_rebuild_preserves_preexisting_unrelated_foreign_key_violations(tmp_path):
    """Legacy orphan rows must not block an unrelated materials repair."""
    engine = _legacy_engine(tmp_path, include_active_version_foreign_key=False)
    migration = _migration()

    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.execute(text(
            "INSERT INTO material_versions(id, material_id, version, status) "
            "VALUES (99, 999, 1, 'ready')"
        ))
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        before = {tuple(row) for row in conn.execute(text("PRAGMA foreign_key_check")).fetchall()}

    migration.up(None, engine)

    with engine.connect() as conn:
        after = {tuple(row) for row in conn.execute(text("PRAGMA foreign_key_check")).fetchall()}
    assert after == before


@pytest.mark.parametrize(("orphan_column", "orphan_value"), [("user_id", 999), ("course_id", 999)])
def test_rebuild_preserves_preexisting_materials_foreign_key_violations(tmp_path, orphan_column, orphan_value):
    """A legacy materials orphan survives even when SQLite renumbers its FK id."""
    engine = _legacy_engine(tmp_path, include_active_version_foreign_key=False)
    migration = _migration()
    values = {"user_id": 1, "course_id": 1, orphan_column: orphan_value}

    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.execute(text(
            "INSERT INTO materials(id, user_id, course_id, filename, file_type, file_path, parse_attempts) "
            "VALUES (9, :user_id, :course_id, 'legacy-orphan.pdf', 'pdf', 'uploads/orphan.pdf', 0)"
        ), values)
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        before = {tuple(row) for row in conn.execute(text("PRAGMA foreign_key_check")).fetchall()}
        before_semantic = migration._foreign_key_violation_identities(conn)

    migration.up(None, engine)

    with engine.connect() as conn:
        after = {tuple(row) for row in conn.execute(text("PRAGMA foreign_key_check")).fetchall()}
        after_semantic = migration._foreign_key_violation_identities(conn)
        foreign_keys = {tuple(row[2:]) for row in conn.execute(text("PRAGMA foreign_key_list(materials)")).fetchall()}
    assert len(before) == len(after) == 1
    assert {entry[:3] for entry in after} == {entry[:3] for entry in before}
    assert before != after  # SQLite may reassign foreign_key_check.fkid during rebuild.
    assert after_semantic == before_semantic
    assert ("material_versions", "active_version_id", "id", "NO ACTION", "NO ACTION", "NONE") in foreign_keys


def test_rebuild_rejects_active_version_violation_introduced_by_new_foreign_key(tmp_path):
    """The semantic comparison still rejects a violation added by migration 024."""
    engine = _legacy_engine(tmp_path, include_active_version_foreign_key=False)
    migration = _migration()
    with engine.begin() as conn:
        conn.execute(text("UPDATE materials SET active_version_id=999 WHERE id=7"))

    with pytest.raises(RuntimeError, match="introduced foreign-key violations"):
        migration.up(None, engine)


def test_schema_repair_does_not_create_database_backup_files(tmp_path):
    """The production migration function only repairs the supplied database."""
    engine = _legacy_engine(tmp_path, include_active_version_foreign_key=False)

    _migration().up(None, engine)

    assert list(tmp_path.glob("*.backup-*")) == []


def test_public_id_constraint_repair_regenerates_empty_and_duplicate_values_idempotently(tmp_path):
    """A deployed table can already autoincrement while its public IDs are unsafe."""
    engine = _legacy_engine(tmp_path)
    migration = _migration()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE materials ADD COLUMN public_id VARCHAR(36)"))
        conn.execute(text("INSERT INTO materials(id, user_id, course_id, filename, file_type, file_path, parse_attempts, public_id) VALUES (9, 1, 1, 'dup.pdf', 'pdf', 'uploads/dup.pdf', 0, 'same-public-id'), (10, 1, 1, 'dup-2.pdf', 'pdf', 'uploads/dup-2.pdf', 0, 'same-public-id')"))
        conn.execute(text("UPDATE materials SET public_id='' WHERE id=7"))

    before = migration.dry_run(None, engine)
    assert before["public_id_column_missing"] is False
    assert before["public_id_not_null_missing"] is True
    assert before["public_id_unique_missing"] is True
    assert before["public_id_null_rows"] == 1
    assert before["public_id_duplicate_rows"] == 1
    assert before["would_change"] > 0

    migration.up(None, engine)
    with engine.connect() as conn:
        snapshot = migration.inspect_materials_schema(conn)
        values = [row[0] for row in conn.execute(text("SELECT public_id FROM materials ORDER BY id")).fetchall()]
        assert snapshot.public_id_exists and snapshot.public_id_not_null and snapshot.public_id_unique
        assert snapshot.public_id_null_rows == snapshot.public_id_duplicate_rows == 0
        assert len(values) == len(set(values)) == 3
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []

    migration.up(None, engine)
    after = migration.dry_run(None, engine)
    assert after["would_change"] == 0
    assert after["public_id_null_rows"] == after["public_id_duplicate_rows"] == 0


def test_public_id_constraint_repair_normalizes_whitespace_only_values(tmp_path):
    """A valid-looking deployed schema can still contain a blank public ID."""
    engine = _legacy_engine(tmp_path)
    migration = _migration()
    migration.up(None, engine)

    with engine.begin() as conn:
        conn.execute(text("UPDATE materials SET public_id='   ' WHERE id=7"))

    before = migration.dry_run(None, engine)
    assert before["public_id_not_null_missing"] is False
    assert before["public_id_unique_missing"] is False
    assert before["public_id_null_rows"] == 1
    assert before["would_change"] > 0

    migration.up(None, engine)
    with engine.connect() as conn:
        snapshot = migration.inspect_materials_schema(conn)
        public_id = conn.execute(text("SELECT public_id FROM materials WHERE id=7")).scalar_one()
        assert public_id.strip()
        assert snapshot.public_id_null_rows == snapshot.public_id_duplicate_rows == 0
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []

    migration.up(None, engine)
    assert migration.dry_run(None, engine)["would_change"] == 0
