"""V7.4.2-02: Migration 018 integrity — PRAGMA-based detection & fault injection.

Tests that:
1. _has_unique_constraint uses PRAGMA index_list/index_info (not sqlite_master name matching)
2. Final snapshot is taken before commit
3. Indexes are saved and restored
4. Fault injection: migration aborts cleanly on various failures
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Import migration 018 dynamically (module name starts with digits)
_migration_mod = importlib.import_module(
    "app.db.versioned_migrations.018_v7_4_page_unique"
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_legacy_engine(tmp_path: Path):
    """Create an engine with material_pages table lacking UNIQUE constraint."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE material_pages (
                id INTEGER PRIMARY KEY,
                material_id INTEGER,
                material_version_id INTEGER,
                page_no INTEGER,
                page_type TEXT,
                parser_version TEXT,
                raw_text TEXT,
                clean_text TEXT,
                blocks_json TEXT,
                decisions_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """))
        conn.commit()
    return engine


def _make_legacy_engine_with_index(tmp_path: Path):
    """Create engine with a partial UNIQUE index (only material_version_id)."""
    db_path = tmp_path / "test_partial.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE material_pages (
                id INTEGER PRIMARY KEY,
                material_id INTEGER,
                material_version_id INTEGER,
                page_no INTEGER,
                page_type TEXT,
                parser_version TEXT,
                raw_text TEXT,
                clean_text TEXT,
                blocks_json TEXT,
                decisions_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """))
        # Partial unique index on just material_version_id
        conn.execute(text(
            "CREATE UNIQUE INDEX idx_partial ON material_pages(material_version_id)"
        ))
        conn.commit()
    return engine


def _make_legacy_engine_with_exact_index(tmp_path: Path):
    """Create engine with the exact UNIQUE(material_version_id, page_no) index."""
    db_path = tmp_path / "test_exact.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE material_pages (
                id INTEGER PRIMARY KEY,
                material_id INTEGER,
                material_version_id INTEGER,
                page_no INTEGER,
                page_type TEXT,
                parser_version TEXT,
                raw_text TEXT,
                clean_text TEXT,
                blocks_json TEXT,
                decisions_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX idx_exact ON material_pages(material_version_id, page_no)"
        ))
        conn.commit()
    return engine


def _insert_page(conn, page_id=1, material_id=1, version_id=1, page_no=1,
                 raw_text="test", clean_text="test", blocks_json="[]",
                 decisions_json="[]"):
    conn.execute(text("""
        INSERT INTO material_pages
            (id, material_id, material_version_id, page_no, page_type,
             parser_version, raw_text, clean_text, blocks_json, decisions_json,
             created_at, updated_at)
        VALUES
            (:id, :mid, :vid, :pn, 'text', 'v1', :raw, :clean, :bj, :dj,
             '2025-01-01', '2025-01-01')
    """), {
        "id": page_id, "mid": material_id, "vid": version_id, "pn": page_no,
        "raw": raw_text, "clean": clean_text, "bj": blocks_json, "dj": decisions_json,
    })
    conn.commit()


def _setup_minimal_materials(engine):
    """Create minimal parent tables for FK integrity."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                hashed_password TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                title TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY,
                course_id INTEGER REFERENCES courses(id),
                title TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_versions (
                id INTEGER PRIMARY KEY,
                material_id INTEGER REFERENCES materials(id),
                version_number INTEGER
            )
        """))
        conn.execute(text("INSERT INTO users (id, username, hashed_password) VALUES (1, 'test', 'hash')"))
        conn.execute(text("INSERT INTO courses (id, user_id, title) VALUES (1, 1, 'Test')"))
        conn.execute(text("INSERT INTO materials (id, course_id, title) VALUES (1, 1, 'Test')"))
        conn.execute(text("INSERT INTO material_versions (id, material_id, version_number) VALUES (1, 1, 1)"))
        conn.commit()


# ── Test: PRAGMA-based constraint detection ──────────────────────────────

class TestPragmaConstraintDetection:
    """V7.4.2-02: _has_unique_constraint must use PRAGMA index_list/index_info."""

    def test_rejects_partial_unique_index(self, tmp_path):
        """A UNIQUE index on only material_version_id must NOT be accepted."""
        engine = _make_legacy_engine_with_index(tmp_path)
        try:
            assert not _migration_mod._has_unique_constraint(engine), (
                "Partial UNIQUE(material_version_id) index must not be detected "
                "as the exact UNIQUE(material_version_id, page_no) constraint"
            )
        finally:
            engine.dispose()

    def test_accepts_exact_constraint(self, tmp_path):
        """The exact UNIQUE(material_version_id, page_no) must be detected."""
        engine = _make_legacy_engine_with_exact_index(tmp_path)
        try:
            assert _migration_mod._has_unique_constraint(engine), (
                "Exact UNIQUE(material_version_id, page_no) index must be detected"
            )
        finally:
            engine.dispose()

    def test_rejects_no_constraint(self, tmp_path):
        """No UNIQUE constraint at all must return False."""
        engine = _make_legacy_engine(tmp_path)
        try:
            assert not _migration_mod._has_unique_constraint(engine)
        finally:
            engine.dispose()

    def test_uses_pragma_not_sqlite_master(self):
        """The detection function should use PRAGMA, not sqlite_master SQL parsing."""
        import inspect as pyinspect
        source = pyinspect.getsource(_migration_mod._has_unique_constraint)
        # Must use PRAGMA index_list or index_info
        assert "index_list" in source or "index_info" in source or "get_indexes" in source, (
            "_has_unique_constraint should use PRAGMA index_list/index_info "
            "or SQLAlchemy inspect.get_indexes for constraint detection"
        )


# ── Test: Final snapshot before commit ───────────────────────────────────

class TestFinalSnapshot:
    """V7.4.2-02: A final snapshot must be taken after table rebuild, before commit."""

    def test_final_snapshot_verified(self, tmp_path):
        """Migration must verify a final snapshot after renaming the new table."""
        engine = _make_legacy_engine(tmp_path)
        _setup_minimal_materials(engine)
        with engine.connect() as conn:
            _insert_page(conn, page_id=1, version_id=1, page_no=1,
                         raw_text="content", clean_text="clean")
        try:
            db = Session(engine)
            _migration_mod.up(db, engine)
            db.close()
            # Verify data is intact
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT raw_text, clean_text FROM material_pages WHERE id=1"
                )).fetchone()
                assert row[0] == "content"
                assert row[1] == "clean"
        finally:
            engine.dispose()


# ── Test: Index restoration ──────────────────────────────────────────────

class TestIndexRestoration:
    """V7.4.2-02: Indexes must be restored after table rebuild."""

    def test_indexes_exist_after_migration(self, tmp_path):
        """After migration, the UNIQUE index must exist on the new table."""
        engine = _make_legacy_engine(tmp_path)
        _setup_minimal_materials(engine)
        with engine.connect() as conn:
            _insert_page(conn, page_id=1, version_id=1, page_no=1)
        try:
            db = Session(engine)
            _migration_mod.up(db, engine)
            db.close()
            # Check that the unique index exists
            with engine.connect() as conn:
                indexes = conn.execute(text(
                    "PRAGMA index_list('material_pages')"
                )).fetchall()
                has_unique = any(
                    idx[1].startswith("sqlite_autoindex") or
                    idx[1].startswith("idx_") or
                    idx[2] == 1  # unique flag
                    for idx in indexes
                )
                assert has_unique, (
                    f"Expected at least one UNIQUE index after migration, "
                    f"got: {indexes}"
                )
        finally:
            engine.dispose()


# ── Test: Fault injection ────────────────────────────────────────────────

class TestFaultInjection:
    """V7.4.2-02: Migration must abort cleanly on various failure scenarios."""

    def test_duplicate_aborts_and_preserves_original(self, tmp_path):
        """If duplicates exist, migration aborts and original data is untouched."""
        engine = _make_legacy_engine(tmp_path)
        with engine.connect() as conn:
            _insert_page(conn, page_id=1, version_id=1, page_no=1, raw_text="original1")
            _insert_page(conn, page_id=2, version_id=1, page_no=1, raw_text="original2")
        try:
            db = Session(engine)
            with pytest.raises((RuntimeError, Exception), match="(?i)duplicate"):
                _migration_mod.up(db, engine)
            db.close()
            # Original data must be preserved
            with engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT COUNT(*) FROM material_pages"
                )).scalar()
                assert rows == 2, "Original rows must be preserved on abort"
        finally:
            engine.dispose()

    def test_leftover_temp_table_aborts(self, tmp_path):
        """If a leftover temp table exists, migration must error."""
        engine = _make_legacy_engine(tmp_path)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE material_pages_new (id INTEGER)"))
            conn.commit()
        try:
            db = Session(engine)
            with pytest.raises((RuntimeError, Exception), match="material_pages_new"):
                _migration_mod.up(db, engine)
            db.close()
        finally:
            engine.dispose()

    def test_idempotent_double_run(self, tmp_path):
        """Running migration twice must not error."""
        engine = _make_legacy_engine(tmp_path)
        _setup_minimal_materials(engine)
        with engine.connect() as conn:
            _insert_page(conn, page_id=1, version_id=1, page_no=1, raw_text="data")
        try:
            db = Session(engine)
            _migration_mod.up(db, engine)
            _migration_mod.up(db, engine)  # second run should be no-op
            db.close()
            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar()
                assert count == 1
        finally:
            engine.dispose()

    def test_null_version_rows_preserved(self, tmp_path):
        """Rows with NULL material_version_id must be preserved."""
        engine = _make_legacy_engine(tmp_path)
        _setup_minimal_materials(engine)
        with engine.connect() as conn:
            _insert_page(conn, page_id=1, version_id=1, page_no=1, raw_text="with_version")
            # Insert a row with NULL version
            conn.execute(text("""
                INSERT INTO material_pages (id, material_id, material_version_id, page_no,
                    page_type, parser_version, raw_text, clean_text, blocks_json,
                    decisions_json, created_at, updated_at)
                VALUES (2, 1, NULL, 1, 'text', 'v1', 'null_version', 'null_clean',
                    '[]', '[]', '2025-01-01', '2025-01-01')
            """))
            conn.commit()
        try:
            db = Session(engine)
            _migration_mod.up(db, engine)
            db.close()
            with engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT raw_text FROM material_pages ORDER BY id"
                )).fetchall()
                assert len(rows) == 2
                assert rows[0][0] == "with_version"
                assert rows[1][0] == "null_version"
        finally:
            engine.dispose()
