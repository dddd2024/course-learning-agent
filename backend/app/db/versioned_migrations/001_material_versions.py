"""Migration 001: Create MaterialVersion rows for historical materials.

For historical ready Materials without a MaterialVersion, create version 1
and bind chunks to it. Also set ``materials.version = 1`` for any material
whose version is NULL or < 1.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "001_material_versions"
description = (
    "Create version 1 for historical ready Materials without a "
    "MaterialVersion, and set materials.version >= 1"
)


def dry_run(db, engine: Engine) -> dict:
    """Report how many materials need version backfill."""
    insp = inspect(engine)
    if "materials" not in insp.get_table_names():
        return {
            "materials_to_migrate": 0,
            "materials_without_version_row": 0,
            "would_change": 0,
        }
    with engine.connect() as conn:
        null_count = conn.execute(text(
            "SELECT COUNT(*) FROM materials "
            "WHERE version IS NULL OR version < 1"
        )).scalar()
        no_mv_count = conn.execute(text(
            "SELECT COUNT(*) FROM materials m "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM material_versions mv WHERE mv.material_id = m.id"
            ")"
        )).scalar() if "material_versions" in insp.get_table_names() else 0
    return {
        "materials_to_migrate": null_count,
        "materials_without_version_row": no_mv_count,
        "would_change": null_count,
    }


def up(db, engine: Engine) -> None:
    """Apply the migration."""
    insp = inspect(engine)
    if "materials" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        # Set version = 1 for materials with NULL or < 1 version.
        conn.execute(text(
            "UPDATE materials SET version = 1 "
            "WHERE version IS NULL OR version < 1"
        ))

        # For materials without any MaterialVersion row, create one.
        if "material_versions" in insp.get_table_names():
            rows = conn.execute(text(
                "SELECT m.id FROM materials m "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM material_versions mv "
                "  WHERE mv.material_id = m.id"
                ")"
            )).fetchall()
            for row in rows:
                material_id = row[0]
                conn.execute(text(
                    "INSERT INTO material_versions "
                    "(material_id, version, status, content_hash, parsed_at) "
                    "VALUES (:mid, 1, 'ready', NULL, "
                    "datetime('now'))"
                ), {"mid": material_id})
                # Update active_version_id on the material.
                vid = conn.execute(text(
                    "SELECT id FROM material_versions "
                    "WHERE material_id = :mid ORDER BY id DESC LIMIT 1"
                ), {"mid": material_id}).scalar()
                conn.execute(text(
                    "UPDATE materials SET active_version_id = :vid "
                    "WHERE id = :mid"
                ), {"vid": vid, "mid": material_id})
