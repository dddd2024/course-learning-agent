"""Persist the strict quiz pass-score contract."""
from sqlalchemy import inspect, text

version_id = "017_v7_quiz_pass_score"
description = "Add durable pass_score to quizzes"


def dry_run(db, engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns = {c["name"] for c in inspector.get_columns("quizzes")} if "quizzes" in tables else set()
    return {"add_columns": int("pass_score" not in columns), "would_change": int("pass_score" not in columns)}


def up(db, engine):
    inspector = inspect(engine)
    if "quizzes" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("quizzes")}
    if "pass_score" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE quizzes ADD COLUMN pass_score INTEGER NOT NULL DEFAULT 60"))
