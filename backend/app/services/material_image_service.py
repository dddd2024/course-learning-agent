"""Image integrity and repeatable PDF image extraction."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage


def image_state(image: MaterialImage) -> tuple[str, str | None]:
    path = Path(settings.UPLOAD_DIR) / image.image_path
    if path.is_file():
        return "ready", None
    return "missing", "MATERIAL_IMAGE_FILE_MISSING"


def image_integrity(db: Session, material: Material) -> dict:
    rows = db.query(MaterialImage).filter(MaterialImage.material_id == material.id).all()
    ready = sum(image_state(row)[0] == "ready" for row in rows)
    return {"material_id": material.id, "total": len(rows), "ready": ready, "missing": len(rows) - ready,
            "status": "ready" if ready == len(rows) else "missing" if rows else "ready"}


def reextract_images(db: Session, material: Material) -> dict:
    if material.file_type.lower() != "pdf":
        return {"material_id": material.id, "status": "forbidden", "code": "IMAGE_EXTRACTION_UNSUPPORTED", "extracted": 0}
    from app.retrieval.image_extractor import extract_images_from_pdf

    source = Path(settings.UPLOAD_DIR) / material.file_path
    if not source.is_file():
        return {"material_id": material.id, "status": "missing", "code": "MATERIAL_FILE_MISSING", "extracted": 0}
    extracted = extract_images_from_pdf(str(source))
    db.query(MaterialImage).filter(MaterialImage.material_id == material.id).delete(synchronize_session=False)
    chunks = db.query(MaterialChunk).filter(MaterialChunk.material_id == material.id, MaterialChunk.is_active == 1).all()
    page_to_chunk = {}
    for chunk in chunks:
        if chunk.page_no:
            page_to_chunk.setdefault(chunk.page_no, chunk.id)
    image_dir = (Path(settings.UPLOAD_DIR) / material.file_path).parent / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    hashes: set[str] = set()
    count = 0
    for index, image in enumerate(extracted):
        if image.perceptual_hash and image.perceptual_hash in hashes:
            continue
        hashes.add(image.perceptual_hash or f"index:{index}")
        filename = f"page{image.page_no}_{index}.{image.format}"
        full_path = image_dir / filename
        full_path.write_bytes(image.image_bytes)
        db.add(MaterialImage(material_id=material.id, course_id=material.course_id,
            chunk_id=page_to_chunk.get(image.page_no), page_no=image.page_no,
            image_filename=filename, image_path=str(full_path.relative_to(Path(settings.UPLOAD_DIR))).replace("\\", "/"),
            width=image.width, height=image.height, format=image.format,
            is_decorative=1 if image.is_decorative else 0, decorative_reason=image.decorative_reason,
            perceptual_hash=image.perceptual_hash, color_variance=image.color_variance, coverage_ratio=image.coverage_ratio))
        count += 1
    db.commit()
    return {"material_id": material.id, "status": "ready", "code": None, "extracted": count}
