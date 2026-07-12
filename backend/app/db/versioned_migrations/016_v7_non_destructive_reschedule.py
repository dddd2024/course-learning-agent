"""Add durable generation and scheduling metadata for V7 re-planning."""
from sqlalchemy import inspect, text

version_id = "016_v7_non_destructive_reschedule"
description = "Preserve multi-plan task history across reschedules"

_PLAN_COLUMNS = {
    "constraints_json": "TEXT NOT NULL DEFAULT '{}'",
    "last_rescheduled_at": "DATETIME",
}
_TASK_COLUMNS = {
    "generation": "INTEGER NOT NULL DEFAULT 1",
    "stable_task_key": "VARCHAR(320)",
    "schedule_status": "VARCHAR(30) NOT NULL DEFAULT 'active'",
    "superseded_by_task_id": "INTEGER",
}

def dry_run(db, engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    plans = {c["name"] for c in inspector.get_columns("multi_course_plans")} if "multi_course_plans" in tables else set()
    tasks = {c["name"] for c in inspector.get_columns("study_tasks")} if "study_tasks" in tables else set()
    missing = [name for name in _PLAN_COLUMNS if name not in plans] + [name for name in _TASK_COLUMNS if name not in tasks]
    return {"add_columns": len(missing), "would_change": len(missing)}

def up(db, engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "multi_course_plans" in tables:
            present = {c["name"] for c in inspector.get_columns("multi_course_plans")}
            for name, sql_type in _PLAN_COLUMNS.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE multi_course_plans ADD COLUMN {name} {sql_type}"))
        if "study_tasks" in tables:
            present = {c["name"] for c in inspector.get_columns("study_tasks")}
            for name, sql_type in _TASK_COLUMNS.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE study_tasks ADD COLUMN {name} {sql_type}"))
