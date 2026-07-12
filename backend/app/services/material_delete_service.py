"""Transactional material deletion with recoverable storage cleanup."""
from __future__ import annotations
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page import MaterialPage


def delete_material(db: Session, material: Material) -> dict[str, int]:
    root = Path(settings.UPLOAD_DIR) / material.file_path
    folder = root.parent
    staged = folder.with_name(folder.name + ".deleting")
    if folder.exists():
        folder.replace(staged)
    try:
        counts = {"images": db.query(MaterialImage).filter(MaterialImage.material_id == material.id).delete(synchronize_session=False), "pages": db.query(MaterialPage).filter(MaterialPage.material_id == material.id).delete(synchronize_session=False), "chunks": db.query(MaterialChunk).filter(MaterialChunk.material_id == material.id).delete(synchronize_session=False), "versions": db.query(MaterialVersion).filter(MaterialVersion.material_id == material.id).delete(synchronize_session=False)}
        db.delete(material)
        db.commit()
    except Exception:
        db.rollback()
        if staged.exists(): staged.replace(folder)
        raise
    if staged.exists():
        import shutil
        shutil.rmtree(staged)
    return counts
