"""Create durable asynchronous quiz-generation jobs."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "026_quiz_generation_jobs"
description = "Persist queued/running/succeeded/failed quiz generation state."


def up(db, engine: Engine) -> None:
    if "quiz_generation_jobs" in inspect(engine).get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE quiz_generation_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                task_id INTEGER REFERENCES study_tasks(id) ON DELETE SET NULL,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE SET NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                progress_stage VARCHAR(40) NOT NULL DEFAULT 'preparing',
                payload_json TEXT NOT NULL,
                provider_calls INTEGER NOT NULL DEFAULT 0,
                error_code VARCHAR(80), error_message TEXT,
                started_at DATETIME, heartbeat_at DATETIME, finished_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        for column in ("user_id", "course_id", "task_id", "quiz_id", "status", "heartbeat_at"):
            conn.execute(text(f"CREATE INDEX ix_quiz_generation_jobs_{column} ON quiz_generation_jobs ({column})"))


def dry_run(db, engine: Engine) -> dict:
    missing = "quiz_generation_jobs" not in inspect(engine).get_table_names()
    return {"missing_table": missing, "would_change": int(missing)}
