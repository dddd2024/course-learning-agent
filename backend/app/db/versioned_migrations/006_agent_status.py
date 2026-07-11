"""Migration 006: Backfill agent run fallback chain.

Backfill ``fallback_chain`` JSON for existing agent runs that were
created before this column existed.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "006_agent_status"
description = "Backfill fallback_chain JSON for existing agent runs"


def dry_run(db, engine: Engine) -> dict:
    insp = inspect(engine)
    if "agent_runs" not in insp.get_table_names():
        return {"agent_runs_to_backfill": 0, "would_change": 0}
    cols = {c["name"] for c in insp.get_columns("agent_runs")}
    if "fallback_chain" not in cols:
        return {"agent_runs_to_backfill": 0, "would_change": 0}
    with engine.connect() as conn:
        null_count = conn.execute(text(
            "SELECT COUNT(*) FROM agent_runs "
            "WHERE fallback_chain IS NULL OR fallback_chain = ''"
        )).scalar()
    return {"agent_runs_to_backfill": null_count, "would_change": null_count}


def up(db, engine: Engine) -> None:
    insp = inspect(engine)
    if "agent_runs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("agent_runs")}
    with engine.begin() as conn:
        if "fallback_chain" in cols:
            conn.execute(text(
                "UPDATE agent_runs SET fallback_chain = '[]' "
                "WHERE fallback_chain IS NULL OR fallback_chain = ''"
            ))
        if "fallback_used" in cols:
            conn.execute(text(
                "UPDATE agent_runs SET fallback_used = 0 "
                "WHERE fallback_used IS NULL"
            ))
