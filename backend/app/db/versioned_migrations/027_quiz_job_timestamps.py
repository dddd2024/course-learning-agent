"""Backfill job timestamps for databases created by early migration 026."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "027_quiz_job_timestamps"
description = "Ensure quiz jobs always receive created/updated timestamps."


def _exists(engine: Engine) -> bool:
    return "quiz_generation_jobs" in inspect(engine).get_table_names()


def up(db, engine: Engine) -> None:
    if not _exists(engine):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE quiz_generation_jobs SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)"))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_quiz_generation_jobs_timestamps"))
        conn.execute(text("""
            CREATE TRIGGER trg_quiz_generation_jobs_timestamps
            AFTER INSERT ON quiz_generation_jobs
            FOR EACH ROW WHEN NEW.created_at IS NULL OR NEW.updated_at IS NULL
            BEGIN
                UPDATE quiz_generation_jobs
                SET created_at = COALESCE(NEW.created_at, CURRENT_TIMESTAMP),
                    updated_at = COALESCE(NEW.updated_at, CURRENT_TIMESTAMP)
                WHERE id = NEW.id;
            END
        """))


def dry_run(db, engine: Engine) -> dict:
    if not _exists(engine):
        return {"null_timestamps": 0, "would_change": 0}
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM quiz_generation_jobs WHERE created_at IS NULL OR updated_at IS NULL")).scalar() or 0
    return {"null_timestamps": count, "would_change": int(count > 0)}
