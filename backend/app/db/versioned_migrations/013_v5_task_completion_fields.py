"""Add manual completion provenance to upgraded SQLite task tables."""
from sqlalchemy import inspect, text

version_id = "013_v5_task_completion_fields"
description = "Add manual_completed_at to historical study tasks"


def dry_run(db, engine):
    inspector = inspect(engine)
    if "study_tasks" not in inspector.get_table_names():
        return {"add_manual_completed_at": 0, "would_change": 0}
    columns = {column["name"] for column in inspector.get_columns("study_tasks")}
    needed = int("manual_completed_at" not in columns)
    return {"add_manual_completed_at": needed, "would_change": needed}


def up(db, engine):
    if dry_run(db, engine)["would_change"]:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE study_tasks ADD COLUMN manual_completed_at DATETIME"))
