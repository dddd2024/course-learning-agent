"""Migration 005: Verify historical citation support.

Verify historical citations; mark unverifiable citations as
``legacy_unverified``.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "005_citation_support"
description = (
    "Verify historical citations; mark unverifiable as legacy_unverified"
)


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "citations" not in insp.get_table_names():
        return {"citations_to_verify": 0, "would_change": 0}
    cols = {c["name"] for c in insp.get_columns("citations")}
    with engine.connect() as conn:
        unverified = 0
        if "support_status" in cols:
            unverified = conn.execute(text(
                "SELECT COUNT(*) FROM citations "
                "WHERE support_status IS NULL "
                "OR support_status = ''"
            )).scalar()
    return {"citations_to_verify": unverified, "would_change": unverified}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    if "citations" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("citations")}
    with engine.begin() as conn:
        if "support_status" in cols:
            conn.execute(text(
                "UPDATE citations SET support_status = 'weak' "
                "WHERE support_status IS NULL OR support_status = ''"
            ))
        if "verification_reason" in cols:
            conn.execute(text(
                "UPDATE citations SET verification_reason = "
                "'legacy_unverified' "
                "WHERE verification_reason IS NULL "
                "AND support_status = 'weak'"
            ))
