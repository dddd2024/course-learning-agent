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
