"""Idempotently backfill PDF reader pages, geometry, page assets, and FTS.

Run from any directory, for example::

    python backend/scripts/backfill_document_reader_assets.py --dry-run
    python backend/scripts/backfill_document_reader_assets.py --material-id 12
    python backend/scripts/backfill_document_reader_assets.py --all --report artifacts/reader-backfill.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import fitz  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.material import Material  # noqa: E402
from app.models.material_page import MaterialPage  # noqa: E402
from app.retrieval.search import rebuild_material_fts  # noqa: E402
from app.services.material_page_asset_service import (  # noqa: E402
    backfill_missing_material_pages,
    ensure_active_page_assets,
    evaluate_page_asset_coverage,
)
from app.services.material_page_catalog_service import build_material_page_catalog  # noqa: E402
from app.services.material_readiness_service import material_readiness  # noqa: E402


def _source(material: Material) -> Path:
    return Path(settings.UPLOAD_DIR) / material.file_path


def _backfill_geometry(db, material: Material, source: Path) -> int:
    rows = db.query(MaterialPage).filter(
        MaterialPage.material_id == material.id,
        MaterialPage.material_version_id == material.active_version_id,
    ).all()
    by_page = {row.page_no: row for row in rows}
    updated = 0
    with fitz.open(str(source)) as pdf:
        for page_no in range(1, len(pdf) + 1):
            row = by_page.get(page_no)
            if row is None:
                continue
            rect = pdf[page_no - 1].rect
            if not row.source_width or not row.source_height:
                row.source_width = float(rect.width)
                row.source_height = float(rect.height)
                updated += 1
    if updated:
        db.commit()
    return updated


def process_material(db, material: Material, *, dry_run: bool) -> dict:
    source = _source(material)
    before_coverage = evaluate_page_asset_coverage(db, material)
    before_catalog = build_material_page_catalog(db, material)
    before_readiness = material_readiness(db, material)
    result = {
        "material_id": material.id,
        "filename": material.filename,
        "expected": before_coverage.get("expected_pages", 0),
        "ready": before_coverage.get("ready_pages", 0),
        "missing": before_coverage.get("missing_page_numbers", []),
        "action": "dry_run" if dry_run else "skipped",
        "error_code": None,
    }
    if not source.is_file():
        result.update(action="unavailable", error_code="SOURCE_FILE_MISSING")
        return result
    if dry_run:
        return result

    try:
        expected_numbers = before_catalog["expected_page_numbers"]
        if before_catalog["synthetic_page_numbers"]:
            backfill_missing_material_pages(db, material, page_numbers=expected_numbers)
        geometry_updated = _backfill_geometry(db, material, source)
        page_result = ensure_active_page_assets(db, material)
        readiness = material_readiness(db, material)
        fts_result = None
        if readiness["assistant"]["degraded"] or (
            readiness["fts_indexed_chunk_count"] != readiness["indexable_chunk_count"]
        ):
            fts_result = rebuild_material_fts(db, material.id)

        coverage = evaluate_page_asset_coverage(db, material)
        catalog = build_material_page_catalog(db, material)
        complete = coverage["status"] == "ready" and not catalog["synthetic_page_numbers"]
        changed = geometry_updated > 0 or before_coverage.get("status") != "ready" or bool(
            before_catalog["synthetic_page_numbers"]
        ) or fts_result is not None
        result.update({
            "expected": coverage["expected_pages"],
            "ready": coverage["ready_pages"],
            "missing": coverage["missing_page_numbers"],
            "action": "repaired" if complete and changed else "skipped" if complete else "failed",
            "geometry_updated": geometry_updated,
            "page_result": {
                key: page_result.get(key)
                for key in (
                    "status", "reader_state", "expected_pages",
                    "ready_pages", "missing_pages", "error_code",
                )
            },
            "fts_result": fts_result,
            "error_code": None if complete else "PAGE_ASSETS_INCOMPLETE",
        })
    except Exception as exc:  # one material must not stop the batch
        db.rollback()
        result.update(action="failed", error_code=type(exc).__name__, error=str(exc))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--material-id", type=int)
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    with SessionLocal() as db:
        query = db.query(Material).filter(
            Material.status == "ready",
            Material.file_type == "pdf",
        )
        if args.material_id:
            query = query.filter(Material.id == args.material_id)
        elif not args.all and not args.dry_run:
            parser.error("正式执行必须指定 --material-id 或 --all")
        materials = query.order_by(Material.id).all()
        items = [process_material(db, material, dry_run=args.dry_run) for material in materials]

    report = {
        "dry_run": args.dry_run,
        "total": len(items),
        "repaired": sum(item["action"] == "repaired" for item in items),
        "skipped": sum(item["action"] == "skipped" for item in items),
        "failed": sum(item["action"] in {"failed", "unavailable"} for item in items),
        "items": items,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
