"""SQLAlchemy engine and session factory."""
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


# SQLite needs the check_same_thread flag disabled so the engine can be
# shared across request-handling threads (and the test client).
# We also set a generous busy_timeout (30s) so concurrent writers wait
# instead of immediately raising "database is locked".
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)


if settings.DATABASE_URL.startswith("sqlite"):
    # Enable WAL (Write-Ahead Logging) mode so readers don't block writers
    # and vice-versa. This dramatically reduces "database is locked" errors
    # when multiple background parse tasks write concurrently.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")  # 30s
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Iterator:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
