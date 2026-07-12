"""V7.4-04: Add title_snapshot and generation columns to multi_course_plan_tasks.

These columns preserve the original title and generation version for
unscheduled tasks (task_id=None) so they display correctly in the detail
view and can be filtered by generation.
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine


VERSION_ID = "020_v7_4_plan_task_snapshot"


def up(db, engine: Engine) -> None:
    """Add title_snapshot and generation columns."""
    with engine.connect() as conn:
        # Check if columns already exist (idempotent).
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(multi_course_plan_tasks)")).fetchall()}
        if "title_snapshot" not in cols:
            conn.execute(text(
                "ALTER TABLE multi_course_plan_tasks ADD COLUMN title_snapshot VARCHAR(255)"
            ))
            conn.commit()
        if "generation" not in cols:
            conn.execute(text(
                "ALTER TABLE multi_course_plan_tasks ADD COLUMN generation INTEGER"
            ))
            conn.commit()


def dry_run(engine: Engine) -> list[str]:
    """Return the SQL statements that would be executed."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(multi_course_plan_tasks)")).fetchall()}
    stmts = []
    if "title_snapshot" not in cols:
        stmts.append("ALTER TABLE multi_course_plan_tasks ADD COLUMN title_snapshot VARCHAR(255)")
    if "generation" not in cols:
        stmts.append("ALTER TABLE multi_course_plan_tasks ADD COLUMN generation INTEGER")
    return stmts
