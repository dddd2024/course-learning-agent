"""E2E-only database/storage fixture helper for V7.5.3 Playwright gates.

The script refuses to run outside ENVIRONMENT=e2e and the isolated run root.
It is invoked by Playwright through a child Python process; production APIs do
not expose fixture mutation endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.e2e_guard import validate_e2e_runtime
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.retrieval.search import remove_from_fts_index


def _guard() -> None:
    validate_e2e_runtime(settings)
    if settings.ENVIRONMENT.lower() != "e2e":
        raise RuntimeError("fixture helper is available only in ENVIRONMENT=e2e")


def _fts_count(db, chunk_ids: list[int]) -> int:
    if not chunk_ids:
        return 0
    try:
        placeholders = ",".join(str(int(value)) for value in chunk_ids)
        return int(
            db.execute(
                text(f"SELECT COUNT(*) FROM material_chunks_fts WHERE chunk_id IN ({placeholders})")
            ).scalar()
            or 0
        )
    except Exception:
        db.rollback()
        return 0


def material_info(material_id: int) -> dict:
    db = SessionLocal()
    try:
        material = db.get(Material, material_id)
        if material is None:
            return {"exists": False, "material_id": material_id}
        chunks = db.query(MaterialChunk).filter(MaterialChunk.material_id == material_id).all()
        file_path = Path(settings.UPLOAD_DIR) / material.file_path
        return {
            "exists": True,
            "material_id": material.id,
            "active_version_id": material.active_version_id,
            "version_number": material.version,
            "file_path": material.file_path,
            "material_dir": str(file_path.parent),
            "chunk_ids": [row.id for row in chunks],
            "counts": {
                "versions": db.query(MaterialVersion).filter(MaterialVersion.material_id == material_id).count(),
                "pages": db.query(MaterialPage).filter(MaterialPage.material_id == material_id).count(),
                "page_assets": db.query(MaterialPageAsset).filter(MaterialPageAsset.material_id == material_id).count(),
                "images": db.query(MaterialImage).filter(MaterialImage.material_id == material_id).count(),
                "chunks": len(chunks),
                "fts": _fts_count(db, [row.id for row in chunks]),
            },
            "material_dir_exists": file_path.parent.exists(),
        }
    finally:
        db.close()


def remove_page_assets(material_id: int, break_first_image: bool) -> dict:
    db = SessionLocal()
    try:
        material = db.get(Material, material_id)
        if material is None or material.active_version_id is None:
            raise RuntimeError("material/active version missing")
        version_id = material.active_version_id
        deleted = (
            db.query(MaterialPageAsset)
            .filter(MaterialPageAsset.material_version_id == version_id)
            .delete(synchronize_session=False)
        )
        source = Path(settings.UPLOAD_DIR) / material.file_path
        page_dir = source.parent / "pages" / f"v{material.version}"
        shutil.rmtree(page_dir, ignore_errors=True)

        broken_image = None
        if break_first_image:
            image = (
                db.query(MaterialImage)
                .filter(
                    MaterialImage.material_version_id == version_id,
                    MaterialImage.render_status == "ready",
                )
                .order_by(MaterialImage.id)
                .first()
            )
            if image is not None:
                image_path = Path(settings.UPLOAD_DIR) / image.image_path
                image_path.unlink(missing_ok=True)
                broken_image = image.id
        db.commit()
        return {
            "deleted_page_assets": deleted,
            "page_dir": str(page_dir),
            "page_dir_exists": page_dir.exists(),
            "broken_image_id": broken_image,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def remove_chunks(material_id: int) -> dict:
    db = SessionLocal()
    try:
        chunk_ids = [
            row[0]
            for row in db.query(MaterialChunk.id)
            .filter(MaterialChunk.material_id == material_id)
            .all()
        ]
        remove_from_fts_index(db, chunk_ids)
        deleted = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.material_id == material_id)
            .delete(synchronize_session=False)
        )
        db.commit()
        return {"chunk_ids": chunk_ids, "deleted_chunks": deleted, "fts_remaining": _fts_count(db, chunk_ids)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def deleted_state(material_id: int, material_dir: str, chunk_ids: list[int]) -> dict:
    db = SessionLocal()
    try:
        return {
            "material": db.query(Material).filter(Material.id == material_id).count(),
            "versions": db.query(MaterialVersion).filter(MaterialVersion.material_id == material_id).count(),
            "pages": db.query(MaterialPage).filter(MaterialPage.material_id == material_id).count(),
            "page_assets": db.query(MaterialPageAsset).filter(MaterialPageAsset.material_id == material_id).count(),
            "images": db.query(MaterialImage).filter(MaterialImage.material_id == material_id).count(),
            "chunks": db.query(MaterialChunk).filter(MaterialChunk.material_id == material_id).count(),
            "fts": _fts_count(db, chunk_ids),
            "material_dir_exists": Path(material_dir).exists(),
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("material-info")
    info.add_argument("material_id", type=int)

    remove_assets = sub.add_parser("remove-page-assets")
    remove_assets.add_argument("material_id", type=int)
    remove_assets.add_argument("--break-first-image", action="store_true")

    remove = sub.add_parser("remove-chunks")
    remove.add_argument("material_id", type=int)

    deleted = sub.add_parser("deleted-state")
    deleted.add_argument("material_id", type=int)
    deleted.add_argument("material_dir")
    deleted.add_argument("chunk_ids_json")

    args = parser.parse_args()
    _guard()
    if args.command == "material-info":
        result = material_info(args.material_id)
    elif args.command == "remove-page-assets":
        result = remove_page_assets(args.material_id, args.break_first_image)
    elif args.command == "remove-chunks":
        result = remove_chunks(args.material_id)
    else:
        result = deleted_state(args.material_id, args.material_dir, json.loads(args.chunk_ids_json))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
