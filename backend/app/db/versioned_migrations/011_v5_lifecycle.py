"""V5 durable parse/multi-plan tables and TaskExecutionEvent cascade indexes."""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.models.parse_job import ParseJob
from app.models.plan import MultiCoursePlan, MultiCoursePlanTask

version_id = "011_v5_lifecycle"
description = "Create durable parse and multi-course planning tables"


def dry_run(db, engine):
    names = set(inspect(engine).get_table_names())
    required = {"parse_jobs", "multi_course_plans", "multi_course_plan_tasks"}
    missing = sorted(required - names)
    return {"tables_to_create": missing, "would_change": len(missing)}


def up(db, engine):
    ParseJob.__table__.create(bind=engine, checkfirst=True)
    MultiCoursePlan.__table__.create(bind=engine, checkfirst=True)
    MultiCoursePlanTask.__table__.create(bind=engine, checkfirst=True)
    # Indexes are safe to add to legacy SQLite databases and make job/event
    # recovery queries deterministic without rewriting historical events.
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_execution_events_task_event_created ON task_execution_events (task_id, event_type, occurred_at)"))
