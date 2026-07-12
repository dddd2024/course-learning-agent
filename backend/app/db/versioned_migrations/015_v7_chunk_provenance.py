"""V7 chunk provenance and versioned material-page uniqueness."""
from sqlalchemy import inspect, text

version_id = "015_v7_chunk_provenance"
description = "Add semantic chunk provenance fields and versioned page uniqueness"

_COLUMNS = {
    "page_start": "INTEGER",
    "page_end": "INTEGER",
    "source_block_ids_json": "TEXT",
    "split_reason": "VARCHAR(40)",
    "chunker_version": "VARCHAR(40)",
}

def dry_run(db, engine):
    inspector = inspect(engine)
    if "material_chunks" not in inspector.get_table_names():
        return {"add_columns": 0, "would_change": 0}
    present = {c["name"] for c in inspector.get_columns("material_chunks")}
    missing = [name for name in _COLUMNS if name not in present]
    return {"add_columns": len(missing), "would_change": len(missing)}

def up(db, engine):
    if "material_chunks" not in inspect(engine).get_table_names():
        return
    present = {c["name"] for c in inspect(engine).get_columns("material_chunks")}
    with engine.begin() as conn:
        for name, sql_type in _COLUMNS.items():
            if name not in present:
                conn.execute(text(f"ALTER TABLE material_chunks ADD COLUMN {name} {sql_type}"))
        conn.execute(text("UPDATE material_chunks SET page_start=page_no WHERE page_start IS NULL"))
        conn.execute(text("UPDATE material_chunks SET page_end=page_no WHERE page_end IS NULL"))
