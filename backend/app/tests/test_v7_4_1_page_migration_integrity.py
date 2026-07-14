"""V7.4.1-01: Page migration integrity tests.

Tests that migration 018 is truly lossless:
1. SHA-256 snapshot of all fields before/after migration matches
2. NULL material_version_id rows are preserved
3. Exact UNIQUE(material_version_id, page_no) constraint is detected
4. Foreign key integrity is verified
5. Leftover temp table causes an error
6. Failure at any step rolls back to original state
7. Chinese text and JSON fields are preserved
8. Multiple materials and versions are preserved
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import Base
from importlib import import_module
mig018 = import_module("app.db.versioned_migrations.018_v7_4_page_unique")
migration_up = mig018.up
_has_unique_constraint = mig018._has_unique_constraint
_compute_snapshot = mig018._compute_snapshot


def _make_legacy_engine(tmp_path):
    """Create a SQLite engine with material_pages table but WITHOUT the UNIQUE constraint."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Rebuild material_pages WITHOUT the UNIQUE constraint to simulate legacy
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE material_pages RENAME TO _mp_old"))
        conn.execute(text("""
            CREATE TABLE material_pages (
                id INTEGER PRIMARY KEY,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                material_version_id INTEGER REFERENCES material_versions(id),
                page_no INTEGER NOT NULL,
                page_type VARCHAR(30) NOT NULL DEFAULT 'text',
                parser_version VARCHAR(32) NOT NULL DEFAULT 'legacy',
                raw_text TEXT,
                clean_text TEXT,
                blocks_json TEXT,
                decisions_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("DROP TABLE _mp_old"))
        conn.execute(text(
            "CREATE INDEX ix_material_pages_material_id ON material_pages (material_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_material_pages_material_version_id ON material_pages (material_version_id)"
        ))
    return engine


def _insert_page(conn, material_id, version_id, page_no, raw_text="hello",
                 clean_text="clean", page_type="text", parser_version="legacy",
                 blocks_json=None, decisions_json=None):
    """Insert a material_page row."""
    conn.execute(text("""
        INSERT INTO material_pages
            (material_id, material_version_id, page_no, page_type, parser_version,
             raw_text, clean_text, blocks_json, decisions_json)
        VALUES
            (:mid, :vid, :pno, :ptype, :pver, :raw, :clean, :blocks, :decisions)
    """), {
        "mid": material_id, "vid": version_id, "pno": page_no,
        "ptype": page_type, "pver": parser_version,
        "raw": raw_text, "clean": clean_text,
        "blocks": blocks_json, "decisions": decisions_json,
    })


def _setup_materials(engine, count=2, versions_per_material=2):
    """Create materials and versions in the DB."""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id, username, password_hash) VALUES (1, 'test', 'hash')"
        ))
        conn.execute(text(
            "INSERT INTO courses (id, user_id, name) VALUES (1, 1, 'test')"
        ))
        for m in range(1, count + 1):
            conn.execute(text(
                "INSERT INTO materials (id, public_id, user_id, course_id, filename, file_path, file_type, status, parse_attempts) "
                f"VALUES ({m}, '00000000-0000-4000-8000-{m:012d}', 1, 1, 'mat{m}.pdf', 'mat{m}.pdf', 'pdf', 'ready', 0)"
            ))
            for v in range(1, versions_per_material + 1):
                vid = (m - 1) * versions_per_material + v
                conn.execute(text(
                    "INSERT INTO material_versions (id, material_id, version, status, content_hash) "
                    f"VALUES ({vid}, {m}, {v}, 'ready', 'hash{vid}')"
                ))


# ---------------------------------------------------------------------------
# 1. SHA-256 snapshot integrity
# ---------------------------------------------------------------------------

class TestSnapshotIntegrity:
    """Migration must preserve a SHA-256 snapshot of all fields."""

    def test_snapshot_unchanged_after_migration(self, tmp_path):
        """All fields (by ID order) must have the same SHA-256 before and after."""
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=2, versions_per_material=2)

        with engine.begin() as conn:
            _insert_page(conn, 1, 1, 1, raw_text="中文页面内容", clean_text="cleaned中文",
                         blocks_json='{"blocks":[]}', decisions_json='{"decisions":[]}')
            _insert_page(conn, 1, 1, 2, raw_text="page 2 content")
            _insert_page(conn, 1, 2, 1, raw_text="version 2 page 1")
            _insert_page(conn, 2, 3, 1, raw_text="material 2 version 1")
            _insert_page(conn, 2, 4, 1, raw_text="material 2 version 2")

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            snapshot_before = _compute_snapshot(engine)

            migration_up(db, engine)

            snapshot_after = _compute_snapshot(engine)

            assert snapshot_before == snapshot_after, (
                "SHA-256 snapshot changed after migration — data was lost or altered"
            )
        finally:
            db.close()

    def test_null_version_rows_preserved(self, tmp_path):
        """Rows with material_version_id IS NULL must all be preserved."""
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=1, versions_per_material=1)

        with engine.begin() as conn:
            _insert_page(conn, 1, None, 1, raw_text="null version page 1")
            _insert_page(conn, 1, None, 1, raw_text="null version page 1 duplicate")
            _insert_page(conn, 1, None, 2, raw_text="null version page 2")
            _insert_page(conn, 1, 1, 1, raw_text="version 1 page 1")

        with engine.connect() as conn:
            count_before = conn.execute(text(
                "SELECT COUNT(*) FROM material_pages WHERE material_version_id IS NULL"
            )).scalar()

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            migration_up(db, engine)
        finally:
            db.close()

        with engine.connect() as conn:
            count_after = conn.execute(text(
                "SELECT COUNT(*) FROM material_pages WHERE material_version_id IS NULL"
            )).scalar()

        assert count_after == count_before, (
            f"NULL version rows changed: {count_before} -> {count_after}"
        )


# ---------------------------------------------------------------------------
# 2. Exact constraint detection
# ---------------------------------------------------------------------------

class TestConstraintDetection:
    """The _has_unique_constraint function must detect the exact constraint."""

    def test_rejects_partial_constraint(self, tmp_path):
        """A UNIQUE constraint on only material_version_id (not page_no) must NOT be detected as complete."""
        engine = _make_legacy_engine(tmp_path)
        # Add a unique index on just material_version_id
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX uq_partial ON material_pages (material_version_id)"
            ))
        assert not _has_unique_constraint(engine), (
            "A UNIQUE(material_version_id) index alone must NOT be detected as the target constraint"
        )

    def test_accepts_exact_constraint(self, tmp_path):
        """A UNIQUE(material_version_id, page_no) constraint must be detected."""
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        Base.metadata.create_all(engine)  # This includes the proper UniqueConstraint
        assert _has_unique_constraint(engine), (
            "The model's UniqueConstraint must be detected"
        )


# ---------------------------------------------------------------------------
# 3. Foreign key integrity
# ---------------------------------------------------------------------------

class TestForeignKeyIntegrity:
    """Foreign key relationships must be intact after migration."""

    def test_foreign_keys_valid_after_migration(self, tmp_path):
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=2, versions_per_material=2)

        with engine.begin() as conn:
            _insert_page(conn, 1, 1, 1)
            _insert_page(conn, 2, 3, 1)

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            migration_up(db, engine)
        finally:
            db.close()

        with engine.connect() as conn:
            # PRAGMA foreign_key_check returns rows with violations
            violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            assert len(violations) == 0, (
                f"Foreign key violations after migration: {violations}"
            )

            # Verify FK references are still valid
            result = conn.execute(text("""
                SELECT p.id, p.material_id, p.material_version_id,
                       m.id as mat_id, mv.id as ver_id
                FROM material_pages p
                LEFT JOIN materials m ON p.material_id = m.id
                LEFT JOIN material_versions mv ON p.material_version_id = mv.id
            """)).fetchall()
            for row in result:
                assert row[3] is not None, f"material_id FK broken for page {row[0]}"


# ---------------------------------------------------------------------------
# 4. Leftover temp table detection
# ---------------------------------------------------------------------------

class TestLeftoverTempTable:
    """A leftover material_pages_new table must cause an error."""

    def test_leftover_temp_table_errors(self, tmp_path):
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=1, versions_per_material=1)

        with engine.begin() as conn:
            _insert_page(conn, 1, 1, 1)
            # Create a leftover temp table
            conn.execute(text("CREATE TABLE material_pages_new (id INTEGER)"))

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            with pytest.raises(RuntimeError, match="material_pages_new"):
                migration_up(db, engine)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 5. Chinese text and JSON fields
# ---------------------------------------------------------------------------

class TestChineseAndJsonPreservation:
    """Chinese text and JSON fields must be preserved exactly."""

    def test_chinese_text_preserved(self, tmp_path):
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=1, versions_per_material=1)

        chinese_raw = "操作系统内存管理：虚拟内存是现代操作系统的核心概念。"
        chinese_clean = "虚拟内存是现代操作系统的核心概念。"
        blocks = json.dumps({"blocks": [{"block_id": "p1b1", "text": "虚拟内存"}]})
        decisions = json.dumps({"decisions": [{"decision": "kept"}]})

        with engine.begin() as conn:
            _insert_page(conn, 1, 1, 1, raw_text=chinese_raw, clean_text=chinese_clean,
                         blocks_json=blocks, decisions_json=decisions)

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            migration_up(db, engine)
        finally:
            db.close()

        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT raw_text, clean_text, blocks_json, decisions_json FROM material_pages WHERE id=1"
            )).fetchone()
            assert row[0] == chinese_raw
            assert row[1] == chinese_clean
            assert json.loads(row[2]) == json.loads(blocks)
            assert json.loads(row[3]) == json.loads(decisions)


# ---------------------------------------------------------------------------
# 6. Duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    """Migration must abort when duplicates exist."""

    def test_aborts_on_duplicates(self, tmp_path):
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=1, versions_per_material=1)

        with engine.begin() as conn:
            _insert_page(conn, 1, 1, 1, raw_text="first")
            _insert_page(conn, 1, 1, 1, raw_text="duplicate")  # Same version+page

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            with pytest.raises(RuntimeError, match="duplicate"):
                migration_up(db, engine)
        finally:
            db.close()

        # Verify original data is intact (rollback)
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar()
            assert count == 2, "Original rows must be preserved after abort"


# ---------------------------------------------------------------------------
# 7. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Running migration twice must not error."""

    def test_double_run(self, tmp_path):
        engine = _make_legacy_engine(tmp_path)
        _setup_materials(engine, count=1, versions_per_material=1)

        with engine.begin() as conn:
            _insert_page(conn, 1, 1, 1)

        from app.core import database as db_module
        db = db_module.SessionLocal()
        try:
            migration_up(db, engine)
            migration_up(db, engine)  # Should be a no-op
        finally:
            db.close()

        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar()
            assert count == 1
