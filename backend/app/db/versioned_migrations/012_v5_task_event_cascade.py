"""Rebuild the legacy SQLite evidence table with the documented cascade."""
from __future__ import annotations

from sqlalchemy import inspect, text

version_id = "012_v5_task_event_cascade"
description = "Rebuild task execution events with task cascade and replay index"


def _has_task_cascade(engine) -> bool:
    try:
        if any(fk.get("referred_table") == "study_tasks" and (fk.get("options", {}).get("ondelete") or "").upper() == "CASCADE"
               for fk in inspect(engine).get_foreign_keys("task_execution_events")):
            return True
        if engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='task_execution_events'")) .scalar_one_or_none() or ""
            return "REFERENCES STUDY_TASKS" in sql.upper() and "ON DELETE CASCADE" in sql.upper()
        return False
    except Exception:
        return False


def dry_run(db, engine):
    names = set(inspect(engine).get_table_names())
    if "task_execution_events" not in names:
        return {"rebuild_task_execution_events": 0, "would_change": 0}
    return {"rebuild_task_execution_events": int(not _has_task_cascade(engine)), "would_change": int(not _has_task_cascade(engine))}


def up(db, engine):
    if engine.dialect.name != "sqlite" or _has_task_cascade(engine):
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_execution_events_task_event_created ON task_execution_events (task_id, event_type, occurred_at)"))
        return
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("""CREATE TABLE task_execution_events_v5 (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES study_tasks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            event_type VARCHAR(50) NOT NULL,
            target_type VARCHAR(30), target_id INTEGER, payload_json TEXT,
            occurred_at DATETIME NOT NULL, created_at DATETIME, updated_at DATETIME
        )"""))
        conn.execute(text("""INSERT INTO task_execution_events_v5
            (id, task_id, user_id, event_type, target_type, target_id, payload_json, occurred_at, created_at, updated_at)
            SELECT id, task_id, user_id, event_type, target_type, target_id, payload_json, occurred_at, created_at, updated_at
            FROM task_execution_events"""))
        conn.execute(text("DROP TABLE task_execution_events"))
        conn.execute(text("ALTER TABLE task_execution_events_v5 RENAME TO task_execution_events"))
        conn.execute(text("CREATE INDEX ix_task_execution_events_task_event_created ON task_execution_events (task_id, event_type, occurred_at)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
