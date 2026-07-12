"""V6-30: Add generation column to knowledge_points for version tracking.

Each regeneration now creates new active KPs with an incremented
generation number and archives the old ones.  The ``generation``
column tracks which generation a KP belongs to.
"""
from sqlalchemy import inspect, text

version_id = "014_v6_kp_generation"
description = "Add generation column to knowledge_points for version tracking"


def dry_run(db, engine):
    inspector = inspect(engine)
    if "knowledge_points" not in inspector.get_table_names():
        return {"add_generation": 0, "would_change": 0}
    columns = {column["name"] for column in inspector.get_columns("knowledge_points")}
    needed = int("generation" not in columns)
    return {"add_generation": needed, "would_change": needed}


def up(db, engine):
    if dry_run(db, engine)["would_change"]:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE knowledge_points ADD COLUMN generation INTEGER DEFAULT 1 NOT NULL"
            ))
