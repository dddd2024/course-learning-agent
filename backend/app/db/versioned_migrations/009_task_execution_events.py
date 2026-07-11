"""Migration 009: create immutable task execution evidence storage."""
from sqlalchemy import inspect, text

version_id = "009_task_execution_events"
description = "Create task execution event evidence table"

def dry_run(db, engine):
    return {"would_change": 0 if "task_execution_events" in inspect(engine).get_table_names() else 1}

def up(db, engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS task_execution_events (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL, event_type VARCHAR(50) NOT NULL, target_type VARCHAR(30), target_id INTEGER, payload_json TEXT, occurred_at DATETIME NOT NULL, created_at DATETIME, updated_at DATETIME)"))
