"""Lightweight column migrations for legacy SQLite databases (no Alembic).

Project uses ``Base.metadata.create_all`` which creates new columns on
fresh DBs but does NOT alter existing tables. This module adds the
``user_focus`` / ``evidence_hash`` columns to ``concept_compare_reports``
when they are missing on an existing dev database, so old local DBs do
not crash with a 500 on compare-report insert.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {
    "user_focus": "VARCHAR(50) DEFAULT 'concept' NOT NULL",
    "evidence_hash": "VARCHAR(64) DEFAULT '' NOT NULL",
}


def ensure_concept_compare_report_columns(engine: Engine) -> None:
    """Add user_focus/evidence_hash to concept_compare_reports if missing.

    Safe to call on: fresh DB (table absent -> skipped), legacy DB (table
    present, columns absent -> ALTER ADD), modern DB (columns present -> no-op).
    """
    insp = inspect(engine)
    if "concept_compare_reports" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    with engine.begin() as conn:
        for col, ddl in _REQUIRED_COLUMNS.items():
            if col not in existing:
                logger.info("adding column %s to concept_compare_reports", col)
                conn.execute(
                    text(
                        f"ALTER TABLE concept_compare_reports "
                        f"ADD COLUMN {col} {ddl}"
                    )
                )


# Material parse-tracking columns added by the error-log/parse-reliability
# plan. create_all adds them on fresh DBs; this patches existing dev DBs.
_MATERIAL_PARSE_COLUMNS = {
    "parse_started_at": "DATETIME",
    "parse_finished_at": "DATETIME",
    "parse_attempts": "INTEGER DEFAULT 0 NOT NULL",
    "last_parse_error": "TEXT",
}

_FIRST_ROUND_COLUMNS = {
    "materials": {"active_version_id": "INTEGER"},
    "material_chunks": {
        "material_version_id": "INTEGER",
        "stable_key": "VARCHAR(128)",
        "content_hash": "VARCHAR(64)",
        "is_active": "INTEGER DEFAULT 1 NOT NULL",
    },
    "knowledge_points": {
        "stable_key": "VARCHAR(320)",
        "title_normalized": "VARCHAR(255)",
        "status": "VARCHAR(20) DEFAULT 'active' NOT NULL",
        "source_version_ids": "TEXT DEFAULT '[]'",
    },
    "quiz_items": {
        "difficulty": "INTEGER",
        "source_evidence_ids": "TEXT DEFAULT '[]'",
        "evidence_snapshot": "TEXT",
    },
    "agent_runs": {
        "requested_provider": "VARCHAR(50)",
        "requested_model": "VARCHAR(100)",
        "actual_provider": "VARCHAR(50)",
        "actual_model": "VARCHAR(100)",
        "fallback_used": "INTEGER DEFAULT 0 NOT NULL",
        "fallback_reason": "TEXT",
        "evidence_status": "VARCHAR(30)",
    },
}


def ensure_first_round_columns(engine: Engine) -> None:
    """Idempotently add first-round compatibility columns to SQLite DBs."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, columns in _FIRST_ROUND_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in columns.items():
                if col not in existing:
                    logger.info("adding column %s to %s", col, table)
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def ensure_material_parse_columns(engine: Engine) -> None:
    """Add parse-tracking columns to ``materials`` if missing (legacy dev DBs).

    Safe to call on: fresh DB (table absent -> skipped), legacy DB (table
    present, columns absent -> ALTER ADD), modern DB (columns present -> no-op).
    """
    insp = inspect(engine)
    if "materials" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("materials")}
    with engine.begin() as conn:
        for col, ddl in _MATERIAL_PARSE_COLUMNS.items():
            if col not in existing:
                logger.info("adding column %s to materials", col)
                conn.execute(
                    text(
                        f"ALTER TABLE materials ADD COLUMN {col} {ddl}"
                    )
                )
