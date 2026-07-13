"""Persist multi-course reschedule runs and their five-category diff items."""
from sqlalchemy import text
from sqlalchemy.engine import Engine

version_id = "021_v7_4_3_reschedule_history"


def up(db, engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS multi_plan_reschedule_runs (
              id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES multi_course_plans(id) ON DELETE CASCADE,
              old_generation INTEGER NOT NULL, new_generation INTEGER NOT NULL, daily_minutes INTEGER NOT NULL,
              status VARCHAR(30) NOT NULL DEFAULT 'completed', created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS multi_plan_reschedule_diff_items (
              id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES multi_plan_reschedule_runs(id) ON DELETE CASCADE,
              category VARCHAR(30) NOT NULL, stable_task_key VARCHAR(320), old_task_id INTEGER, new_task_id INTEGER,
              old_date DATE, new_date DATE, old_generation INTEGER, new_generation INTEGER, reason VARCHAR(255),
              title VARCHAR(255) NOT NULL, course_id INTEGER REFERENCES courses(id),
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reschedule_run_plan ON multi_plan_reschedule_runs(plan_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reschedule_diff_run ON multi_plan_reschedule_diff_items(run_id)"))


def dry_run(db, engine: Engine) -> dict:
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    return {"create_runs": "multi_plan_reschedule_runs" not in tables, "create_diff_items": "multi_plan_reschedule_diff_items" not in tables}
