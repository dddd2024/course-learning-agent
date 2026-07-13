"""Add page-level visual assets and image occurrence integrity metadata."""
from sqlalchemy import text
from sqlalchemy.engine import Engine

version_id = "023_v7_5_page_assets"
description = "Store versioned page renders and image occurrence metadata."


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def up(db, engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_page_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                material_version_id INTEGER NOT NULL,
                page_no INTEGER NOT NULL,
                asset_path VARCHAR(500), mime_type VARCHAR(64) NOT NULL DEFAULT 'image/png',
                width INTEGER, height INTEGER, dpi INTEGER NOT NULL DEFAULT 144,
                sha256 VARCHAR(64), render_status VARCHAR(30) NOT NULL DEFAULT 'pending',
                error_code VARCHAR(100), created_at DATETIME, updated_at DATETIME,
                UNIQUE(material_version_id, page_no)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_material_page_assets_material_id ON material_page_assets(material_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_material_page_assets_version_id ON material_page_assets(material_version_id)"))
        image_columns = _columns(conn, "material_images")
        for name, ddl in {
            "material_version_id": "INTEGER",
            "xref": "INTEGER",
            "bbox_json": "TEXT",
            "sha256": "VARCHAR(64)",
            "render_status": "VARCHAR(30) NOT NULL DEFAULT 'ready'",
            "error_code": "VARCHAR(100)",
        }.items():
            if name not in image_columns:
                conn.execute(text(f"ALTER TABLE material_images ADD COLUMN {name} {ddl}"))


def dry_run(db, engine: Engine) -> dict:
    with engine.connect() as conn:
        return {
            "page_asset_table_exists": bool(conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_page_assets'")).scalar()),
            "missing_image_columns": sorted({"material_version_id", "xref", "bbox_json", "sha256", "render_status", "error_code"} - _columns(conn, "material_images")),
        }
