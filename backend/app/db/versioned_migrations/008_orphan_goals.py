"""Migration 008: Clean orphan study goals.

Identify and clean goals that have no tasks. In dry-run mode, reports
the count of orphan goals. When applied, deletes them.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "008_orphan_goals"
description = "Identify and clean goals with no tasks"


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "study_goals" not in tables or "study_tasks" not in tables:
        return {"orphan_goals": 0, "would_change": 0}
    with engine.connect() as conn:
        orphan_count = conn.execute(text(
            "SELECT COUNT(*) FROM study_goals g "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM study_tasks t WHERE t.goal_id = g.id"
            ")"
        )).scalar()
    return {"orphan_goals": orphan_count, "would_change": orphan_count}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "study_goals" not in tables:
        return
    with engine.begin() as conn:
        if "study_tasks" in tables:
            conn.execute(text(
                "DELETE FROM study_goals "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM study_tasks t WHERE t.goal_id = study_goals.id"
                ")"
            ))
