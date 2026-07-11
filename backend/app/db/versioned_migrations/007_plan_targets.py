"""Migration 007: Migrate old study tasks to legacy target format.

Migrate old tasks to the legacy ``target_type`` / ``target_id`` format
so they are not orphaned when the new task targeting system is used.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "007_plan_targets"
description = "Migrate old tasks to legacy target format"


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "study_tasks" not in insp.get_table_names():
        return {"tasks_to_migrate": 0, "would_change": 0}
    cols = {c["name"] for c in insp.get_columns("study_tasks")}
    if "target_type" not in cols:
        return {"tasks_to_migrate": 0, "would_change": 0}
    with engine.connect() as conn:
        null_count = conn.execute(text(
            "SELECT COUNT(*) FROM study_tasks "
            "WHERE target_type IS NULL"
        )).scalar()
    return {"tasks_to_migrate": null_count, "would_change": null_count}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    if "study_tasks" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("study_tasks")}
    with engine.begin() as conn:
        if "target_type" in cols:
            conn.execute(text(
                "UPDATE study_tasks SET target_type = 'legacy' "
                "WHERE target_type IS NULL"
            ))
        if "execution_status" in cols:
            conn.execute(text(
                "UPDATE study_tasks SET execution_status = 'pending' "
                "WHERE execution_status IS NULL OR execution_status = ''"
            ))
