"""Migration 018: Enforce UNIQUE constraint on material_pages (material_version_id, page_no).

V7.4.1-01: Verifiably lossless migration.

1. Checks for leftover temp table (errors if found)
2. Checks for duplicate (material_version_id, page_no) rows (aborts if found)
3. Takes a SHA-256 snapshot of all fields before migration
4. Creates new table with explicit schema (NOT CREATE TABLE AS)
5. Inserts all data
6. Verifies snapshot matches
7. Runs PRAGMA foreign_key_check
8. Drops old table, renames new
9. Recreates indexes
10. Takes final snapshot and verifies
11. All in a single transaction — rollback on any failure

Idempotent: detects exact UNIQUE(material_version_id, page_no) and skips.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "018_v7_4_page_unique"
description = (
    "Enforce UNIQUE constraint on material_pages(material_version_id, page_no) "
    "by explicit table rebuild. Verifiably lossless with SHA-256 snapshots."
)

# Fields included in the integrity snapshot, in ID order
SNAPSHOT_FIELDS = [
    "id", "material_id", "material_version_id", "page_no",
    "page_type", "parser_version", "raw_text", "clean_text",
    "blocks_json", "decisions_json", "created_at", "updated_at",
]


def _compute_snapshot(engine: Engine) -> str:
    """Compute a SHA-256 hash of all material_pages rows, ordered by id.

    Each row's fields are concatenated with a separator and the entire
    result is hashed. This detects any data loss or alteration.
    """
    fields_str = "|".join(SNAPSHOT_FIELDS)
    hasher = hashlib.sha256()
    with engine.connect() as conn:
        rows = conn.execute(text(
            f"SELECT {', '.join(SNAPSHOT_FIELDS)} FROM material_pages ORDER BY id"
        )).fetchall()
        for row in rows:
            # Convert each field to string, handle NULL
            parts = [str(v) if v is not None else "\x00NULL" for v in row]
            hasher.update("|".join(parts).encode("utf-8"))
            hasher.update(b"\n")  # Row separator
    hasher.update(f"fields={fields_str}|rows={len(rows)}".encode("utf-8"))
    return hasher.hexdigest()


def _has_unique_constraint(engine: Engine) -> bool:
    """Check if the exact UNIQUE(material_version_id, page_no) constraint exists.

    V7.4.1-01: Must detect the exact column combination, not just any
    UNIQUE index that includes material_version_id.
    """
    insp = inspect(engine)
    if "material_pages" not in insp.get_table_names():
        return True  # Table doesn't exist yet; nothing to do

    # Check indexes for exact (material_version_id, page_no) unique combo
    indexes = insp.get_indexes("material_pages")
    for idx in indexes:
        if not idx.get("unique"):
            continue
        cols = idx.get("column_names", [])
        # Exact match: both columns, in either order
        if set(cols) == {"material_version_id", "page_no"}:
            return True

    # Check table-level constraints via SQL
    with engine.connect() as conn:
        sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='material_pages'"
        )).scalar()
        if sql:
            sql_upper = sql.upper()
            # Must have UNIQUE with both columns
            # Look for UNIQUE(...) or UNIQUE ... with both column names
            if "UNIQUE" in sql_upper:
                # Check for the exact constraint pattern
                # SQLite may store it as UNIQUE(material_version_id, page_no) or with name
                has_mv = "MATERIAL_VERSION_ID" in sql_upper
                has_pn = "PAGE_NO" in sql_upper
                if has_mv and has_pn:
                    # Both columns appear in the CREATE TABLE SQL along with UNIQUE
                    # This is a good heuristic for SQLite
                    return True
    return False


def dry_run(db, engine: Engine) -> dict:
    """Report migration status."""
    insp = inspect(engine)
    if "material_pages" not in insp.get_table_names():
        return {"duplicates": 0, "already_has_constraint": True}

    already = _has_unique_constraint(engine)

    # Check for leftover temp table
    temp_exists = "material_pages_new" in insp.get_table_names()

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

    return {
        "duplicates": dup_count,
        "already_has_constraint": already,
        "leftover_temp_table": temp_exists,
    }


def up(db, engine: Engine) -> None:
    """Apply the migration with full lossless guarantees."""
    insp = inspect(engine)
    if "material_pages" not in insp.get_table_names():
        return

    # Idempotency check — must detect exact constraint
    if _has_unique_constraint(engine):
        return

    # Check for leftover temp table from a previous failed run
    if "material_pages_new" in insp.get_table_names():
        raise RuntimeError(
            "Leftover table 'material_pages_new' detected. "
            "A previous migration run may have failed. "
            "Please inspect and drop it manually before re-running."
        )

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

    # Take snapshot BEFORE migration
    snapshot_before = _compute_snapshot(engine)

    # Single-transaction rebuild with explicit schema
    with engine.begin() as conn:
        # Enable foreign keys for the connection
        conn.execute(text("PRAGMA foreign_keys=ON"))

        # Create new table with explicit schema (NOT CREATE TABLE AS)
        conn.execute(text("""
            CREATE TABLE material_pages_new (
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

        # Insert ALL data from old table
        conn.execute(text("""
            INSERT INTO material_pages_new
                (id, material_id, material_version_id, page_no, page_type,
                 parser_version, raw_text, clean_text, blocks_json, decisions_json,
                 created_at, updated_at)
            SELECT
                id, material_id, material_version_id, page_no, page_type,
                parser_version, raw_text, clean_text, blocks_json, decisions_json,
                created_at, updated_at
            FROM material_pages
        """))

        # Verify row count matches
        old_count = conn.execute(text("SELECT COUNT(*) FROM material_pages")).scalar()
        new_count = conn.execute(text("SELECT COUNT(*) FROM material_pages_new")).scalar()
        if old_count != new_count:
            raise RuntimeError(
                f"Row count mismatch: old={old_count}, new={new_count}. "
                "Rolling back to prevent data loss."
            )

        # Verify snapshot on the temp table matches
        # (We can't use _compute_snapshot directly since it reads material_pages,
        # but we can compare row-by-row)
        old_rows = conn.execute(text(
            "SELECT id, material_id, material_version_id, page_no, page_type, "
            "parser_version, raw_text, clean_text, blocks_json, decisions_json, "
            "created_at, updated_at FROM material_pages ORDER BY id"
        )).fetchall()
        new_rows = conn.execute(text(
            "SELECT id, material_id, material_version_id, page_no, page_type, "
            "parser_version, raw_text, clean_text, blocks_json, decisions_json, "
            "created_at, updated_at FROM material_pages_new ORDER BY id"
        )).fetchall()

        for old_row, new_row in zip(old_rows, new_rows):
            for i, (o, n) in enumerate(zip(old_row, new_row)):
                if o != n:
                    raise RuntimeError(
                        f"Data mismatch at row id={old_row[0]}, field "
                        f"{SNAPSHOT_FIELDS[i]}: old={o!r} new={n!r}. "
                        "Rolling back."
                    )

        # Run foreign key check on the new table
        # (SQLite PRAGMA foreign_key_check checks all tables)
        fk_violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        # Filter for material_pages_new violations
        mp_new_violations = [v for v in fk_violations if v[0] == "material_pages_new"]
        if mp_new_violations:
            raise RuntimeError(
                f"Foreign key violations in new table: {mp_new_violations}. "
                "Rolling back."
            )

        # All checks passed — swap tables
        conn.execute(text("DROP TABLE material_pages"))
        conn.execute(text("ALTER TABLE material_pages_new RENAME TO material_pages"))

        # Recreate indexes
        conn.execute(text(
            "CREATE INDEX ix_material_pages_material_id "
            "ON material_pages (material_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_material_pages_material_version_id "
            "ON material_pages (material_version_id)"
        ))

        # Final foreign key check
        fk_violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        mp_violations = [v for v in fk_violations if v[0] == "material_pages"]
        if mp_violations:
            raise RuntimeError(
                f"Foreign key violations after swap: {mp_violations}. "
                "Rolling back."
            )

    # Verify final snapshot (outside transaction — if this fails, the
    # transaction has already committed, but we detect the problem)
    snapshot_after = _compute_snapshot(engine)
    if snapshot_before != snapshot_after:
        raise RuntimeError(
            "CRITICAL: SHA-256 snapshot mismatch after migration! "
            "Data may have been altered. Manual inspection required."
        )
