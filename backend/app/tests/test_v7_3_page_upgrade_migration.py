"""V7.3-01 P1-06: Page version unique constraint migration.

Tests that an upgraded database has the same UNIQUE(material_version_id,
page_no) constraint as a fresh database.
"""
from __future__ import annotations

import tempfile
import gc
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.db.schema_migrations import run_schema_migrations


def _make_engine(db_path: str):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_fresh_db_has_page_version_unique_constraint():
    """A fresh database must have the unique constraint on material_pages."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fresh.db"
        engine = _make_engine(str(db_path))
        try:
            Base.metadata.create_all(engine)
            insp = inspect(engine)
            constraints = insp.get_unique_constraints("material_pages")
            constraint_columns = [c["column_names"] for c in constraints]
            assert ["material_version_id", "page_no"] in constraint_columns, \
                f"UNIQUE(material_version_id, page_no) not found in {constraint_columns}"
        finally:
            engine.dispose()


def test_upgraded_db_gets_page_version_unique_constraint():
    """An upgraded V6 database must gain the unique constraint after migration."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "upgraded.db"
        engine = _make_engine(str(db_path))
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE material_pages RENAME TO material_pages_old"))
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
                    FROM material_pages_old
                """))
                conn.execute(text("DROP TABLE material_pages_old"))

            insp = inspect(engine)
            constraints_before = insp.get_unique_constraints("material_pages")
            constraint_cols_before = [c["column_names"] for c in constraints_before]
            assert ["material_version_id", "page_no"] not in constraint_cols_before

            run_schema_migrations(engine)

            insp = inspect(engine)
            constraints_after = insp.get_unique_constraints("material_pages")
            constraint_cols_after = [c["column_names"] for c in constraints_after]
            assert ["material_version_id", "page_no"] in constraint_cols_after, \
                f"UNIQUE(material_version_id, page_no) not created by migration. Found: {constraint_cols_after}"
        finally:
            engine.dispose()


def test_migration_is_idempotent():
    """Running the migration twice must not fail."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "idempotent.db"
        engine = _make_engine(str(db_path))
        try:
            Base.metadata.create_all(engine)
            run_schema_migrations(engine)
            run_schema_migrations(engine)
            insp = inspect(engine)
            constraints = insp.get_unique_constraints("material_pages")
            constraint_cols = [c["column_names"] for c in constraints]
            assert ["material_version_id", "page_no"] in constraint_cols
        finally:
            engine.dispose()


def test_migration_detects_duplicate_pages_before_constraint():
    """Migration must detect duplicate (material_version_id, page_no) rows."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "dup.db"
        engine = _make_engine(str(db_path))
        try:
            # Create tables WITHOUT the unique constraint (simulate V6)
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE material_pages RENAME TO material_pages_old"))
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
                    FROM material_pages_old
                """))
                conn.execute(text("DROP TABLE material_pages_old"))

            Session = sessionmaker(bind=engine)
            session = Session()
            material = Material(
                user_id=1, course_id=1, filename="test.pdf",
                file_type="pdf", file_path="test.pdf", status="ready",
            )
            session.add(material)
            session.flush()
            version = MaterialVersion(
                material_id=material.id, version=1,
                status="ready", content_hash="abc123",
            )
            session.add(version)
            session.flush()
            material_id, version_id = material.id, version.id
            session.commit()
            session.close()
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO material_pages
                    (material_id, material_version_id, page_no, page_type, parser_version, raw_text, clean_text)
                    VALUES (:material_id, :version_id, 1, 'text', 'test', 'test', 'test'),
                           (:material_id, :version_id, 1, 'text', 'test', 'test', 'test')
                """), {"material_id": material_id, "version_id": version_id})

            # V7.4-01: Migration must ABORT on duplicates, not delete them
            import pytest as _pytest
            with _pytest.raises(RuntimeError, match="duplicate"):
                run_schema_migrations(engine)

            # Verify NO rows were deleted (safe migration preserves data)
            with engine.begin() as conn:
                result = conn.execute(text(
                    "SELECT material_version_id, page_no, COUNT(*) as cnt "
                    "FROM material_pages GROUP BY material_version_id, page_no "
                    "HAVING cnt > 1"
                )).fetchall()
                assert len(result) > 0, "Duplicates should still exist (migration must not delete)"
        finally:
            engine.dispose()
            gc.collect()


def test_fresh_and_upgraded_schema_are_equivalent():
    """Fresh DB schema must match upgraded DB schema for material_pages."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh_engine = _make_engine(str(Path(tmp) / "fresh2.db"))
        upgrade_engine = _make_engine(str(Path(tmp) / "upgraded2.db"))
        try:
            Base.metadata.create_all(fresh_engine)
            Base.metadata.create_all(upgrade_engine)
            with upgrade_engine.begin() as conn:
                conn.execute(text("ALTER TABLE material_pages RENAME TO material_pages_old"))
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
                    FROM material_pages_old
                """))
                conn.execute(text("DROP TABLE material_pages_old"))
            run_schema_migrations(upgrade_engine)

            fresh_insp = inspect(fresh_engine)
            upgrade_insp = inspect(upgrade_engine)

            fresh_cols = {c["name"] for c in fresh_insp.get_columns("material_pages")}
            upgrade_cols = {c["name"] for c in upgrade_insp.get_columns("material_pages")}
            assert fresh_cols == upgrade_cols, \
                f"Column mismatch: fresh={fresh_cols}, upgraded={upgrade_cols}"

            fresh_uc = sorted(
                [tuple(sorted(c["column_names"])) for c in fresh_insp.get_unique_constraints("material_pages")]
            )
            upgrade_uc = sorted(
                [tuple(sorted(c["column_names"])) for c in upgrade_insp.get_unique_constraints("material_pages")]
            )
            assert fresh_uc == upgrade_uc, \
                f"Unique constraint mismatch: fresh={fresh_uc}, upgraded={upgrade_uc}"
        finally:
            fresh_engine.dispose()
            upgrade_engine.dispose()
