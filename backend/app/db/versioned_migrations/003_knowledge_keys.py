"""Migration 003: Backfill knowledge point keys.

Backfill ``stable_key`` and ``source_version_ids`` for knowledge points
that were created before these columns existed.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "003_knowledge_keys"
description = (
    "Backfill stable_key and source_version_ids for knowledge points"
)


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "knowledge_points" not in insp.get_table_names():
        return {"knowledge_points_to_backfill": 0, "would_change": 0}
    cols = {c["name"] for c in insp.get_columns("knowledge_points")}
    with engine.connect() as conn:
        null_sk = 0
        if "stable_key" in cols:
            null_sk = conn.execute(text(
                "SELECT COUNT(*) FROM knowledge_points "
                "WHERE stable_key IS NULL OR stable_key = ''"
            )).scalar()
        null_svi = 0
        if "source_version_ids" in cols:
            null_svi = conn.execute(text(
                "SELECT COUNT(*) FROM knowledge_points "
                "WHERE source_version_ids IS NULL OR source_version_ids = ''"
            )).scalar()
    total = max(null_sk, null_svi)
    return {"knowledge_points_to_backfill": total, "would_change": total}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    if "knowledge_points" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("knowledge_points")}
    with engine.begin() as conn:
        if "stable_key" in cols:
            conn.execute(text(
                "UPDATE knowledge_points "
                "SET stable_key = 'kp_' || course_id || '_' || id "
                "WHERE stable_key IS NULL OR stable_key = ''"
            ))

        if "source_version_ids" in cols:
            conn.execute(text(
                "UPDATE knowledge_points "
                "SET source_version_ids = '[]' "
                "WHERE source_version_ids IS NULL OR source_version_ids = ''"
            ))
