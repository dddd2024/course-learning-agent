"""Add nullable source-page geometry for selectable PDF text layers."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

version_id = "025_document_reader_geometry"
description = "Store source page width and height on material_pages."


def _missing(engine: Engine) -> list[str]:
    if "material_pages" not in inspect(engine).get_table_names():
        return []
    columns = {column["name"] for column in inspect(engine).get_columns("material_pages")}
    return sorted({"source_width", "source_height"} - columns)


def up(db, engine: Engine) -> None:
    with engine.begin() as conn:
        for column in _missing(engine):
            conn.execute(text(f"ALTER TABLE material_pages ADD COLUMN {column} FLOAT"))


def dry_run(db, engine: Engine) -> dict:
    missing = _missing(engine)
    return {"missing_columns": missing, "would_change": len(missing)}
