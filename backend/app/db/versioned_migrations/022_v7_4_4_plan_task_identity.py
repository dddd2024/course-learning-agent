"""Add durable identity fields for scheduled and unscheduled plan entries."""
from sqlalchemy import text
from sqlalchemy.engine import Engine


version_id = "022_v7_4_4_plan_task_identity"


def up(db, engine: Engine) -> None:
    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(multi_course_plan_tasks)")
            ).fetchall()
        }
        if "stable_task_key" not in columns:
            conn.execute(text(
                "ALTER TABLE multi_course_plan_tasks ADD COLUMN stable_task_key VARCHAR(320)"
            ))
        if "task_type_snapshot" not in columns:
            conn.execute(text(
                "ALTER TABLE multi_course_plan_tasks ADD COLUMN task_type_snapshot VARCHAR(30)"
            ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_multi_plan_task_stable_key "
            "ON multi_course_plan_tasks(stable_task_key)"
        ))


def dry_run(db, engine: Engine) -> dict:
    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(multi_course_plan_tasks)")
            ).fetchall()
        }
    return {
        "add_stable_task_key": "stable_task_key" not in columns,
        "add_task_type_snapshot": "task_type_snapshot" not in columns,
    }
