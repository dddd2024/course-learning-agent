"""Repair legacy page catalogues and material AUTOINCREMENT identity."""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.material import Material
from app.services.material_page_asset_service import backfill_missing_material_pages
from app.services.material_page_catalog_service import resolve_expected_page_numbers

version_id = "024_v7_5_2_page_catalog_recovery"
description = "Backfill legacy PDF pages and preserve material IDs after deletes"


def _legacy_pdf_materials(session: Session):
    return session.query(Material).filter(
        Material.file_type == "pdf", Material.active_version_id.isnot(None),
    ).all()


def _catalog_stats(session: Session) -> dict:
    materials_scanned = materials_with_missing_pages = missing_page_rows = 0
    for material in _legacy_pdf_materials(session):
        materials_scanned += 1
        expected = resolve_expected_page_numbers(session, material)["expected_page_numbers"]
        if not expected:
            continue
        from app.models.material_page import MaterialPage
        existing = {row[0] for row in session.query(MaterialPage.page_no).filter(
            MaterialPage.material_id == material.id,
            MaterialPage.material_version_id == material.active_version_id,
        ).all()}
        absent = set(expected) - existing
        if absent:
            materials_with_missing_pages += 1
            missing_page_rows += len(absent)
    return {
        "materials_scanned": materials_scanned,
        "materials_with_missing_pages": materials_with_missing_pages,
        "missing_page_rows": missing_page_rows,
    }


def _materials_has_autoincrement(engine: Engine) -> bool:
    with engine.connect() as conn:
        sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='materials'")).scalar() or ""
    return "AUTOINCREMENT" in sql.upper()


def dry_run(db, engine: Engine) -> dict:
    session = Session(bind=engine)
    try:
        stats = _catalog_stats(session)
    finally:
        session.close()
    stats["material_autoincrement_missing"] = not _materials_has_autoincrement(engine)
    stats["would_change"] = stats["missing_page_rows"] + int(stats["material_autoincrement_missing"])
    return stats


def _rebuild_materials_for_autoincrement(engine: Engine) -> None:
    if _materials_has_autoincrement(engine):
        return
    with engine.connect() as conn:
        original = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='materials'")).scalar()
        indexes = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='materials' AND sql IS NOT NULL")).scalars().all()
    if not original:
        return
    rewritten = re.sub(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?materials", "CREATE TABLE materials__v752_new", original, count=1, flags=re.I)
    rewritten = re.sub(r"\bid\s+INTEGER\s+PRIMARY\s+KEY(?!\s+AUTOINCREMENT)", "id INTEGER PRIMARY KEY AUTOINCREMENT", rewritten, count=1, flags=re.I)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(rewritten))
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(materials)")).fetchall()]
        column_sql = ", ".join(f'"{name}"' for name in columns)
        conn.execute(text(f"INSERT INTO materials__v752_new ({column_sql}) SELECT {column_sql} FROM materials"))
        conn.execute(text("DROP TABLE materials"))
        conn.execute(text("ALTER TABLE materials__v752_new RENAME TO materials"))
        for index_sql in indexes:
            conn.execute(text(index_sql))
        max_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM materials")).scalar_one()
        conn.execute(text("DELETE FROM sqlite_sequence WHERE name='materials'"))
        conn.execute(text("INSERT INTO sqlite_sequence(name, seq) VALUES ('materials', :seq)"), {"seq": max_id})
        violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        if violations:
            raise RuntimeError(f"foreign_key_check failed: {violations}")
        conn.execute(text("PRAGMA foreign_keys=ON"))


def up(db, engine: Engine) -> None:
    session = Session(bind=engine)
    try:
        for material in _legacy_pdf_materials(session):
            expected = resolve_expected_page_numbers(session, material)["expected_page_numbers"]
            if expected:
                backfill_missing_material_pages(session, material, page_numbers=expected)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    _rebuild_materials_for_autoincrement(engine)
