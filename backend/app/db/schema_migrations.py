"""Versioned migration tracking table (MIG-V3-01).

Provides a ``schema_migrations`` table that records which versioned
migrations have been applied. Each row stores the version string,
the timestamp it was applied, and a checksum for integrity.

Functions:
- :func:`ensure_schema_migrations_table`: create the table if missing.
- :func:`get_applied_versions`: return a set of applied version strings.
- :func:`is_applied`: check if a specific version has been applied.
- :func:`record_version`: mark a version as applied.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_schema_migrations_table(engine: Engine) -> None:
    """Create the ``schema_migrations`` table if it does not exist."""
    insp = inspect(engine)
    if "schema_migrations" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE schema_migrations ("
                "  version VARCHAR(255) PRIMARY KEY,"
                "  applied_at DATETIME NOT NULL,"
                "  checksum VARCHAR(64) NOT NULL"
                ")"
            ))


def get_applied_versions(engine: Engine) -> set[str]:
    """Return a set of all applied version strings."""
    insp = inspect(engine)
    if "schema_migrations" not in insp.get_table_names():
        return set()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def is_applied(engine: Engine, version: str) -> bool:
    """Return True if *version* is already in the ``schema_migrations`` table."""
    return version in get_applied_versions(engine)


def record_version(engine: Engine, version: str) -> None:
    """Record that *version* has been applied.

    Uses ``INSERT OR IGNORE`` so calling this on an already-applied
    version is a no-op (idempotent).
    """
    checksum = hashlib.sha256(version.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT OR IGNORE INTO schema_migrations "
            "(version, applied_at, checksum) VALUES (:v, :t, :c)"
        ), {"v": version, "t": now, "c": checksum})


# ---------------------------------------------------------------------------
# V7.3-01 P1-06: Page version unique constraint
# ---------------------------------------------------------------------------

_PAGE_VERSION_MIGRATION = "018_v7_3_page_version_constraints"
_CHUNK_FRAGMENTS_MIGRATION = "019_v7_3_chunk_source_fragments"


def _has_unique_constraint(engine: Engine, table: str, columns: list[str]) -> bool:
    """Return True if *table* has a UNIQUE constraint on *columns*."""
    insp = inspect(engine)
    try:
        constraints = insp.get_unique_constraints(table)
    except Exception:
        return False
    for c in constraints:
        if sorted(c["column_names"]) == sorted(columns):
            return True
    return False


def _ensure_page_version_unique(engine: Engine) -> None:
    """Ensure material_pages has UNIQUE(material_version_id, page_no).

    On SQLite, adding a constraint to an existing table requires a
    table rebuild.  Duplicate rows (same material_version_id + page_no)
    are de-duplicated by keeping the row with the lowest ``id``.
    """
    if _has_unique_constraint(engine, "material_pages", ["material_version_id", "page_no"]):
        return

    with engine.begin() as conn:
        # Step 1: detect and remove duplicate rows (keep lowest id)
        conn.execute(text(
            "DELETE FROM material_pages WHERE id NOT IN ("
            "  SELECT MIN(id) FROM material_pages "
            "  WHERE material_version_id IS NOT NULL "
            "  GROUP BY material_version_id, page_no"
            ")"
        ))
        # Also remove duplicates where material_version_id IS NULL
        # (keep one per page_no per material)
        conn.execute(text(
            "DELETE FROM material_pages WHERE id NOT IN ("
            "  SELECT MIN(id) FROM material_pages "
            "  WHERE material_version_id IS NULL "
            "  GROUP BY material_id, page_no"
            ")"
        ))

        # Step 2: rebuild table with the unique constraint
        conn.execute(text("ALTER TABLE material_pages RENAME TO _material_pages_old"))
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
                FOREIGN KEY(material_version_id) REFERENCES material_versions(id),
                UNIQUE(material_version_id, page_no)
            )
        """))
        conn.execute(text(
            "INSERT INTO material_pages SELECT * FROM _material_pages_old"
        ))
        conn.execute(text("DROP TABLE _material_pages_old"))


def run_schema_migrations(engine: Engine) -> None:
    """Run all pending schema migrations.

    Currently applies:
    - 018_v7_3_page_version_constraints: UNIQUE(material_version_id, page_no)
    - 019_v7_3_chunk_source_fragments: source_fragments_json column on material_chunks
    """
    ensure_schema_migrations_table(engine)
    if not is_applied(engine, _PAGE_VERSION_MIGRATION):
        _ensure_page_version_unique(engine)
        record_version(engine, _PAGE_VERSION_MIGRATION)
    if not is_applied(engine, _CHUNK_FRAGMENTS_MIGRATION):
        _ensure_chunks_source_fragments(engine)
        record_version(engine, _CHUNK_FRAGMENTS_MIGRATION)


def _has_column(engine: Engine, table: str, column: str) -> bool:
    """Return True if *table* has *column*."""
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False
    return column in cols


def _ensure_chunks_source_fragments(engine: Engine) -> None:
    """Add source_fragments_json column to material_chunks if missing."""
    if _has_column(engine, "material_chunks", "source_fragments_json"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE material_chunks ADD COLUMN source_fragments_json TEXT"
        ))
