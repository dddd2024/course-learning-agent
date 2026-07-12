from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def test_legacy_task_events_are_rebuilt_with_cascade(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE study_tasks (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE task_execution_events (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL, event_type VARCHAR(50) NOT NULL, target_type VARCHAR(30), target_id INTEGER, payload_json TEXT, occurred_at DATETIME NOT NULL, created_at DATETIME, updated_at DATETIME)"))
        conn.execute(text("INSERT INTO users VALUES (1)")); conn.execute(text("INSERT INTO study_tasks VALUES (1)"))
        conn.execute(text("INSERT INTO task_execution_events (id,task_id,user_id,event_type,occurred_at) VALUES (1,1,1,'target_loaded','2026-01-01')"))
    from app.db.versioned_migrations import load_migrations
    migration = next(item for item in load_migrations() if item.version_id == "012_v5_task_event_cascade")
    assert migration.dry_run(None, engine)["would_change"] == 1
    migration.up(None, engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM study_tasks WHERE id=1"))
        assert conn.execute(text("SELECT count(*) FROM task_execution_events")).scalar_one() == 0
    assert migration.dry_run(None, engine)["would_change"] == 0
    engine.dispose()
