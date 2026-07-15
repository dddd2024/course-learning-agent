"""V7.4-01: Safe migration tests.

Tests that:
- Migration 018 (page version UNIQUE enforcement) aborts on duplicates instead of deleting
- Migration 018 preserves all rows when no duplicates exist
- Migration 018 is idempotent (running twice doesn't error)
- Migration 019 (source_fragments_json column) is idempotent
- Both migrations are discovered by load_migrations()
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text, inspect

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import Base
from app.db.versioned_migrations import load_migrations, MIGRATION_MODULES


def _make_engine(tmp_path, with_unique=True):
    """Create a fresh SQLite engine with all models.

    If with_unique=False, rebuilds material_pages WITHOUT the UNIQUE
    constraint to simulate a legacy V6 database.
    """
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    if not with_unique:
        # Rebuild material_pages without the UNIQUE constraint
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE material_pages RENAME TO _mp_old"))
            conn.execute(text("""
                CREATE TABLE material_pages (
                    id INTEGER PRIMARY KEY,
                    material_id INTEGER NOT NULL,
                    material_version_id INTEGER,
                    page_no INTEGER NOT NULL,
                    page_type VARCHAR(30) DEFAULT 'text',
                    parser_version VARCHAR(32) DEFAULT 'legacy',
                    raw_text TEXT,
                    clean_text TEXT,
                    blocks_json TEXT,
                    decisions_json TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(material_id) REFERENCES materials(id),
                    FOREIGN KEY(material_version_id) REFERENCES material_versions(id)
                )
            """))
            conn.execute(text("""
                INSERT INTO material_pages
                (id, material_id, material_version_id, page_no, page_type, parser_version,
                 raw_text, clean_text, blocks_json, decisions_json, created_at, updated_at)
                SELECT id, material_id, material_version_id, page_no, page_type, parser_version,
                       raw_text, clean_text, blocks_json, decisions_json, created_at, updated_at
                FROM _mp_old
            """))
            conn.execute(text("DROP TABLE _mp_old"))
    return engine


def _seed_materials(engine):
    """Insert minimal material + version rows using ORM."""
    from app.models.user import User
    from app.models.course import Course
    from app.models.material import Material, MaterialVersion
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        user = User(username="testuser", password_hash="x")
        session.add(user)
        session.flush()
        course = Course(user_id=user.id, name="TestCourse")
        session.add(course)
        session.flush()
        material = Material(
            user_id=user.id,
            course_id=course.id,
            filename="test.txt",
            file_type="txt",
            file_path="test.txt",
            status="ready",
        )
        session.add(material)
        session.flush()
        version = MaterialVersion(
            material_id=material.id,
            version=1,
            status="ready",
        )
        session.add(version)
        session.commit()
        return material.id, version.id


def test_migration_018_aborts_on_duplicates(tmp_path):
    """Migration 018 must abort when duplicate (material_version_id, page_no) rows exist."""
    engine = _make_engine(tmp_path, with_unique=False)
    material_id, version_id = _seed_materials(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO material_pages (material_id, material_version_id, page_no, page_type, parser_version, created_at, updated_at) "
            "VALUES "
            f"({material_id}, {version_id}, 1, 'text', 'legacy', '2026-01-01', '2026-01-01'), "
            f"({material_id}, {version_id}, 1, 'text', 'legacy', '2026-01-01', '2026-01-02')"
        ))

    migrations = load_migrations()
    mig_018 = [m for m in migrations if m.version_id == "018_v7_4_page_unique"]
    assert len(mig_018) == 1, f"Migration 018 not found. Available: {[m.version_id for m in migrations]}"

    with pytest.raises(Exception) as exc_info:
        mig_018[0].up(None, engine)
    assert "duplicate" in str(exc_info.value).lower() or "abort" in str(exc_info.value).lower()

    # Verify NO rows were deleted
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar()
        assert count == 2, f"Expected 2 rows preserved, got {count}"


def test_migration_018_preserves_all_rows_when_no_duplicates(tmp_path):
    """Migration 018 must enforce UNIQUE without losing any rows."""
    engine = _make_engine(tmp_path, with_unique=False)
    material_id, version_id = _seed_materials(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO material_pages (material_id, material_version_id, page_no, page_type, parser_version, created_at, updated_at) "
            "VALUES "
            f"({material_id}, {version_id}, 1, 'text', 'legacy', '2026-01-01', '2026-01-01'), "
            f"({material_id}, {version_id}, 2, 'text', 'legacy', '2026-01-01', '2026-01-01'), "
            f"({material_id}, {version_id}, 3, 'text', 'legacy', '2026-01-01', '2026-01-01'), "
            f"({material_id}, {version_id}, 4, 'text', 'legacy', '2026-01-01', '2026-01-01')"
        ))

    migrations = load_migrations()
    mig_018 = [m for m in migrations if m.version_id == "018_v7_4_page_unique"][0]
    mig_018.up(None, engine)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar()
        assert count == 4, f"Expected 4 rows preserved, got {count}"


def test_migration_018_idempotent(tmp_path):
    """Running migration 018 twice must not raise."""
    engine = _make_engine(tmp_path)
    migrations = load_migrations()
    mig_018 = [m for m in migrations if m.version_id == "018_v7_4_page_unique"][0]

    mig_018.up(None, engine)
    mig_018.up(None, engine)  # Second run should be a no-op


def test_migration_019_source_fragments_idempotent(tmp_path):
    """Migration 019 (source_fragments_json) must be idempotent."""
    engine = _make_engine(tmp_path)
    migrations = load_migrations()
    mig_019 = [m for m in migrations if m.version_id == "019_v7_4_chunk_fragments"][0]

    mig_019.up(None, engine)
    mig_019.up(None, engine)

    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("material_chunks")]
    assert "source_fragments_json" in columns


def test_migrations_discovered_by_migrate_py():
    """Both migrations 018 and 019 must be discovered by load_migrations()."""
    migrations = load_migrations()
    version_ids = [m.version_id for m in migrations]
    assert "018_v7_4_page_unique" in version_ids, f"018 not in {version_ids}"
    assert "019_v7_4_chunk_fragments" in version_ids, f"019 not in {version_ids}"


def test_migration_018_in_migration_modules_list():
    """Migration modules list must include 018 and 019."""
    assert "018_v7_4_page_unique" in MIGRATION_MODULES
    assert "019_v7_4_chunk_fragments" in MIGRATION_MODULES
