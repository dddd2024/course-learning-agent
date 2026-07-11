"""Migration 004: Normalize historical quiz evidence.

Normalize historical choice/multiple_choice answers; mark unverifiable
quiz items as legacy.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "004_quiz_evidence"
description = (
    "Normalize historical choice/multiple_choice answers; "
    "mark unverifiable as legacy"
)


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "quiz_items" not in insp.get_table_names():
        return {"quiz_items_to_normalise": 0, "would_change": 0}
    cols = {c["name"] for c in insp.get_columns("quiz_items")}
    with engine.connect() as conn:
        unverified = 0
        if "verification_status" in cols:
            unverified = conn.execute(text(
                "SELECT COUNT(*) FROM quiz_items "
                "WHERE verification_status IS NULL "
                "OR verification_status = ''"
            )).scalar()
        elif "source_evidence" in cols:
            unverified = conn.execute(text(
                "SELECT COUNT(*) FROM quiz_items "
                "WHERE source_evidence IS NULL "
                "OR source_evidence = '' "
                "OR source_evidence = '[]'"
            )).scalar()
    return {"quiz_items_to_normalise": unverified, "would_change": unverified}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    if "quiz_items" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("quiz_items")}
    with engine.begin() as conn:
        # Set verification_status for items missing it.
        if "verification_status" in cols:
            conn.execute(text(
                "UPDATE quiz_items SET verification_status = 'verified' "
                "WHERE verification_status IS NULL "
                "OR verification_status = ''"
            ))

        # Mark items without evidence as legacy.
        if "source_evidence" in cols:
            conn.execute(text(
                "UPDATE quiz_items "
                "SET source_evidence = '[]' "
                "WHERE source_evidence IS NULL "
                "OR source_evidence = ''"
            ))

        # Set rubric_json for items missing it.
        if "rubric_json" in cols:
            conn.execute(text(
                "UPDATE quiz_items SET rubric_json = '[]' "
                "WHERE rubric_json IS NULL OR rubric_json = ''"
            ))
