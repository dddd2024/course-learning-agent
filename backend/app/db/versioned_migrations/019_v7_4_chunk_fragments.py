"""Migration 019: Add source_fragments_json column to material_chunks.

V7.4-01 P0-02: Formal versioned migration for the source_fragments_json
column that was previously added via a raw ALTER TABLE in
schema_migrations.py. This ensures the column is tracked in the
migration chain and is discoverable by migrate.py.

Idempotent: checks if column already exists before adding.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "019_v7_4_chunk_fragments"
description = (
    "Add source_fragments_json TEXT column to material_chunks for "
    "block-level provenance tracking. Idempotent."
)


def _has_column(engine: Engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "material_chunks" not in insp.get_table_names():
        return {"column_exists": False, "table_exists": False}
    return {"column_exists": _has_column(engine, "material_chunks", "source_fragments_json")}


def up(db, engine: Engine) -> None:
    """Apply the migration."""
    insp = inspect(engine)
    if "material_chunks" not in insp.get_table_names():
        return

    if _has_column(engine, "material_chunks", "source_fragments_json"):
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE material_chunks ADD COLUMN source_fragments_json TEXT"
        ))
