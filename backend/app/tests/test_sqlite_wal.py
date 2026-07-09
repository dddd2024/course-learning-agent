"""Test that SQLite WAL mode is enabled on the engine."""
from app.core.database import engine
from sqlalchemy import text


def test_sqlite_wal_mode():
    """Engine connections should have WAL journal_mode enabled."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert result == "wal", f"Expected WAL mode, got {result}"


def test_sqlite_busy_timeout():
    """Engine connections should have busy_timeout >= 30000ms."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert result >= 30000, f"Expected busy_timeout >= 30000, got {result}"
