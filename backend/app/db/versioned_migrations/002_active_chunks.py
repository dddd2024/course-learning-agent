"""Migration 002: Backfill active chunk columns.

Backfill ``active_version_id``, ``material_version_id``, ``stable_key``,
``content_hash``, and ``is_active`` for chunks that were created before
these columns existed.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "002_active_chunks"
description = (
    "Backfill active_version_id, material_version_id, stable_key, "
    "content_hash, is_active for material chunks"
)


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "material_chunks" not in insp.get_table_names():
        return {"chunks_to_normalise": 0, "would_change": 0}
    cols = {c["name"] for c in insp.get_columns("material_chunks")}
    with engine.connect() as conn:
        null_mv = 0
        if "material_version_id" in cols:
            null_mv = conn.execute(text(
                "SELECT COUNT(*) FROM material_chunks "
                "WHERE material_version_id IS NULL"
            )).scalar()
        null_sk = 0
        if "stable_key" in cols:
            null_sk = conn.execute(text(
                "SELECT COUNT(*) FROM material_chunks "
                "WHERE stable_key IS NULL OR stable_key = ''"
            )).scalar()
    total = max(null_mv, null_sk)
    return {"chunks_to_normalise": total, "would_change": total}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    if "material_chunks" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("material_chunks")}
    with engine.begin() as conn:
        # Backfill material_version_id from the material's version 1.
        if "material_version_id" in cols and "material_versions" in insp.get_table_names():
            conn.execute(text(
                "UPDATE material_chunks "
                "SET material_version_id = ("
                "  SELECT mv.id FROM material_versions mv "
                "  WHERE mv.material_id = material_chunks.material_id "
                "  AND mv.version = 1 LIMIT 1"
                ") WHERE material_version_id IS NULL"
            ))

        # Backfill stable_key for chunks missing one.
        if "stable_key" in cols:
            conn.execute(text(
                "UPDATE material_chunks "
                "SET stable_key = 'mc_' || material_id || '_' || chunk_index "
                "WHERE stable_key IS NULL OR stable_key = ''"
            ))

        # Backfill content_hash for chunks missing one.
        if "content_hash" in cols:
            conn.execute(text(
                "UPDATE material_chunks "
                "SET content_hash = "
                "  substr(hex(zeroblob(8)), 1, 16) "
                "WHERE content_hash IS NULL OR content_hash = ''"
            ))

        # Set is_active = 1 for all chunks (default).
        if "is_active" in cols:
            conn.execute(text(
                "UPDATE material_chunks SET is_active = 1 "
                "WHERE is_active IS NULL"
            ))
