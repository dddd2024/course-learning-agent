"""Versioned migration tracking table (MIG-V3-01).

Provides a ``schema_migrations`` table that records which versioned
migrations have been applied. Each row stores the version string,
the timestamp it was applied, and a checksum for integrity.

Functions:
- :func:`ensure_schema_migrations_table`: create the table if missing.
- :func:`get_applied_versions`: return a set of applied version strings.
- :func:`is_applied`: check if a specific version has been applied.
- :func:`record_version`: mark a version as applied.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_schema_migrations_table(engine: Engine) -> None:
    """Create the ``schema_migrations`` table if it does not exist."""
    insp = inspect(engine)
    if "schema_migrations" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE schema_migrations ("
                "  version VARCHAR(255) PRIMARY KEY,"
                "  applied_at DATETIME NOT NULL,"
                "  checksum VARCHAR(64) NOT NULL"
                ")"
            ))


def get_applied_versions(engine: Engine) -> set[str]:
    """Return a set of all applied version strings."""
    insp = inspect(engine)
    if "schema_migrations" not in insp.get_table_names():
        return set()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def is_applied(engine: Engine, version: str) -> bool:
    """Return True if *version* is already in the ``schema_migrations`` table."""
    return version in get_applied_versions(engine)


def record_version(engine: Engine, version: str) -> None:
    """Record that *version* has been applied.

    Uses ``INSERT OR IGNORE`` so calling this on an already-applied
    version is a no-op (idempotent).
    """
    checksum = hashlib.sha256(version.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT OR IGNORE INTO schema_migrations "
            "(version, applied_at, checksum) VALUES (:v, :t, :c)"
        ), {"v": version, "t": now, "c": checksum})


# ---------------------------------------------------------------------------
# V7.4-01: Dangerous _ensure_page_version_unique removed.
# Migrations 018 and 019 are now formal versioned migrations
# discovered by migrate.py via load_migrations().
# ---------------------------------------------------------------------------


def run_schema_migrations(engine: Engine) -> None:
    """Run all pending schema migrations via the formal versioned migration chain.

    V7.4-01: The destructive _ensure_page_version_unique and
    _ensure_chunks_source_fragments functions have been removed.
    Migrations 018_v7_4_page_unique and 019_v7_4_chunk_fragments
    are now discovered by migrate.py through load_migrations().

    This function is kept for backward compatibility but now delegates
    to the versioned migration system.
    """
    ensure_schema_migrations_table(engine)

    from app.db.versioned_migrations import load_migrations

    applied = get_applied_versions(engine)
    for migration in load_migrations():
        vid = migration.version_id
        if vid in applied:
            continue
        # Run the migration's up() function
        migration.up(None, engine)
        record_version(engine, vid)


def _has_column(engine: Engine, table: str, column: str) -> bool:
    """Return True if *table* has *column*."""
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False
    return column in cols
