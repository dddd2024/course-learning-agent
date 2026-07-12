"""Migration 018: Enforce UNIQUE constraint on material_pages (material_version_id, page_no).

V7.4-01 P0-01/P0-02: Replaces the destructive _ensure_page_version_unique
in schema_migrations.py which DELETEd duplicate rows. This migration:

1. Checks for duplicate (material_version_id, page_no) rows
2. If duplicates exist, ABORTS with an error (no data loss)
3. If no duplicates, rebuilds the table with the UNIQUE constraint
4. Idempotent: detects existing constraint and skips

This migration is non-destructive: it never deletes user data.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "018_v7_4_page_unique"
description = (
    "Enforce UNIQUE constraint on material_pages(material_version_id, page_no) "
    "by table rebuild. Aborts if duplicates exist; never deletes data."
)


def _has_unique_constraint(engine: Engine) -> bool:
    """Check if the UNIQUE constraint already exists."""
    insp = inspect(engine)
    if "material_pages" not in insp.get_table_names():
        return True  # Table doesn't exist yet; nothing to do
    indexes = insp.get_indexes("material_pages")
    for idx in indexes:
        if idx.get("unique") and "material_version_id" in idx.get("column_names", []):
            return True
    # Also check table-level constraints
    with engine.connect() as conn:
        sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='material_pages'"
        )).scalar()
        if sql and "UNIQUE" in sql.upper() and "material_version_id" in sql:
            return True
    return False


def dry_run(db, engine: Engine) -> dict:
    """Report how many duplicate pages exist."""
    insp = inspect(engine)
    if "material_pages" not in insp.get_table_names():
        return {"duplicates": 0, "already_has_constraint": True}

    already = _has_unique_constraint(engine)
    with engine.connect() as conn:
        dup_count = conn.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT material_version_id, page_no, COUNT(*) as c
                FROM material_pages
                WHERE material_version_id IS NOT NULL
                GROUP BY material_version_id, page_no
                HAVING c > 1
            )
        """)).scalar()
    return {"duplicates": dup_count, "already_has_constraint": already}


def up(db, engine: Engine) -> None:
    """Apply the migration."""
    insp = inspect(engine)
    if "material_pages" not in insp.get_table_names():
        return

    # Idempotency check
    if _has_unique_constraint(engine):
        return

    # Check for duplicates — ABORT if found (do NOT delete)
    with engine.connect() as conn:
        dup_rows = conn.execute(text("""
            SELECT material_version_id, page_no, COUNT(*) as c
            FROM material_pages
            WHERE material_version_id IS NOT NULL
            GROUP BY material_version_id, page_no
            HAVING c > 1
            LIMIT 5
        """)).fetchall()

    if dup_rows:
        examples = ", ".join(
            f"(version_id={r[0]}, page_no={r[1]}, count={r[2]})"
            for r in dup_rows
        )
        raise RuntimeError(
            f"Cannot add UNIQUE constraint: {len(dup_rows)} duplicate "
            f"(material_version_id, page_no) groups found. "
            f"Examples: {examples}. "
            f"Manual intervention required — migration aborted to prevent data loss."
        )

    # No duplicates: rebuild table with UNIQUE constraint
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE material_pages_new AS
            SELECT * FROM material_pages
        """))
        conn.execute(text("DROP TABLE material_pages"))
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(material_version_id, page_no)
            )
        """))
        conn.execute(text("""
            INSERT INTO material_pages
            SELECT * FROM material_pages_new
        """))
        conn.execute(text("DROP TABLE material_pages_new"))
        # Recreate indexes
        conn.execute(text(
            "CREATE INDEX ix_material_pages_material_id "
            "ON material_pages (material_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_material_pages_material_version_id "
            "ON material_pages (material_version_id)"
        ))
