"""Create page-level material storage for V5 layout parsing."""
from sqlalchemy import inspect
from app.models.material_page import MaterialPage

version_id = "010_v5_pages"
description = "Create material_pages for layout-aware parsing"

def dry_run(db, engine):
    return {"create_material_pages": int("material_pages" not in inspect(engine).get_table_names()), "would_change": int("material_pages" not in inspect(engine).get_table_names())}

def up(db, engine):
    MaterialPage.__table__.create(bind=engine, checkfirst=True)
