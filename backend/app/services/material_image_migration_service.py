"""Migration helpers for legacy unversioned material images."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.material import MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage


def migrate_legacy_images(db: Session, *, commit: bool = True) -> dict:
    """Bind unversioned images when provenance is unambiguous, else quarantine."""
    result = {
        "bound_from_chunk": 0,
        "bound_single_version": 0,
        "quarantined": 0,
        "remaining_null_ready": 0,
    }
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

    if commit:
        db.commit()
    else:
        db.flush()

    result["remaining_null_ready"] = (
        db.query(MaterialImage)
        .filter(
            MaterialImage.material_version_id.is_(None),
            MaterialImage.render_status == "ready",
        )
        .count()
    )
    return result
