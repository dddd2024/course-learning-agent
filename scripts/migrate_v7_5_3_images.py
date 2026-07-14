"""Migrate legacy MaterialImage rows that have no material_version_id.

Safe classification rules:
1. bind to the referenced chunk's version when chunk_id resolves uniquely;
2. otherwise bind to the material's only version when exactly one exists;
3. otherwise quarantine the row so active readers do not expose ambiguous data.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from app.core.database import SessionLocal
from app.models.material import MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage


def migrate() -> dict:
    db = SessionLocal()
    result = {
        "bound_from_chunk": 0,
        "bound_single_version": 0,
        "quarantined": 0,
        "remaining_null_ready": 0,
    }
    try:
        rows = db.query(MaterialImage).filter(MaterialImage.material_version_id.is_(None)).all()
        for image in rows:
            target_version_id = None
            if image.chunk_id:
                chunk = db.query(MaterialChunk).filter(MaterialChunk.id == image.chunk_id).first()
                if chunk and chunk.material_id == image.material_id and chunk.material_version_id:
                    target_version_id = chunk.material_version_id
                    result["bound_from_chunk"] += 1

            if target_version_id is None:
                versions = (
                    db.query(MaterialVersion.id)
                    .filter(MaterialVersion.material_id == image.material_id)
                    .all()
                )
                if len(versions) == 1:
                    target_version_id = versions[0][0]
                    result["bound_single_version"] += 1

            if target_version_id is not None:
                image.material_version_id = target_version_id
                if image.render_status == "quarantined":
                    image.render_status = "ready"
                    image.error_code = None
            else:
                image.render_status = "quarantined"
                image.error_code = "LEGACY_IMAGE_VERSION_AMBIGUOUS"
                result["quarantined"] += 1

        db.commit()
        result["remaining_null_ready"] = (
            db.query(MaterialImage)
            .filter(
                MaterialImage.material_version_id.is_(None),
                MaterialImage.render_status == "ready",
            )
            .count()
        )
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(migrate(), ensure_ascii=False, indent=2))
