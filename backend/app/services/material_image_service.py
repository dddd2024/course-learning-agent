"""Image integrity and repeatable PDF image extraction."""
from __future__ import annotations

from pathlib import Path
import hashlib
import io
import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page_asset import MaterialPageAsset


def image_state(image: MaterialImage) -> tuple[str, str | None]:
    path = Path(settings.UPLOAD_DIR) / image.image_path
    if not path.is_file() or path.stat().st_size == 0:
        return "missing", "MATERIAL_IMAGE_FILE_MISSING"
    try:
        from PIL import Image
        with Image.open(io.BytesIO(path.read_bytes())) as decoded:
            decoded.verify()
        if image.sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != image.sha256:
            return "missing", "MATERIAL_IMAGE_HASH_MISMATCH"
        return "ready", None
    except Exception:
        return "missing", "MATERIAL_IMAGE_DECODE_FAILED"


def _page_asset_ready(asset: MaterialPageAsset) -> bool:
    if asset.render_status != "ready" or not asset.asset_path:
        return False
    path = Path(settings.UPLOAD_DIR) / asset.asset_path
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        from PIL import Image
        payload = path.read_bytes()
        with Image.open(io.BytesIO(payload)) as decoded:
            decoded.verify()
        return not asset.sha256 or hashlib.sha256(payload).hexdigest() == asset.sha256
    except Exception:
        return False


def image_integrity(db: Session, material: Material) -> dict:
    if material.active_version_id:
        rows = db.query(MaterialImage).filter(
            MaterialImage.material_id == material.id,
            MaterialImage.material_version_id == material.active_version_id,
        ).all()
        assets = db.query(MaterialPageAsset).filter(
            MaterialPageAsset.material_id == material.id,
            MaterialPageAsset.material_version_id == material.active_version_id,
        ).all()
    else:
        rows = db.query(MaterialImage).filter(
            MaterialImage.material_id == material.id,
        ).all()
        assets = []
    ready = sum(image_state(row)[0] == "ready" for row in rows)
    total = len(rows)
    missing = total - ready
    page_ready = sum(_page_asset_ready(asset) for asset in assets)
    page_total = len(assets)
    page_missing = page_total - page_ready
    # page_fallback_ready requires full page coverage: every page asset
    # must be ready, not just a subset.
    page_fallback_ready = page_total > 0 and page_ready == page_total
    if page_fallback_ready and (total == 0 or missing > 0):
        status = "page_fallback_ready"
    elif total == 0 and page_total == 0:
        status = "missing"
    elif total == 0:
        status = "missing"
    elif missing == 0:
        status = "ready"
    elif missing < total:
        status = "partial"
    else:
        status = "missing"
    return {
        "material_id": material.id,
        "total": total,
        "ready": ready,
        "missing": missing,
        "page_assets": page_total,
        "page_assets_ready": page_ready,
        "expected_pages": page_total,
        "ready_pages": page_ready,
        "missing_pages": page_missing,
        "status": status,
    }


def reextract_images(
    db: Session,
    material: Material,
    *,
    image_dir: Path | None = None,
    material_version_id: int | None = None,
    commit: bool = True,
) -> dict:
    """Extract images into ``image_dir`` and stage their metadata.

    The public re-extraction endpoint uses the defaults and commits as before.
    The parser supplies a private staging directory with ``commit=False`` so a
    cancellation cannot publish new image metadata before the corresponding
    material version is activated.

    V7.5.1-04: Only deletes and rebuilds images for the target version,
    not all versions. This prevents old-version images from being
    accidentally removed when re-extracting for the current version.
    """
    if material.file_type.lower() != "pdf":
        return {"material_id": material.id, "status": "forbidden", "code": "IMAGE_EXTRACTION_UNSUPPORTED", "found": 0, "extracted": 0}
    from app.retrieval.image_extractor import extract_images_from_pdf

    source = Path(settings.UPLOAD_DIR) / material.file_path
    if not source.is_file():
        return {"material_id": material.id, "status": "missing", "code": "MATERIAL_FILE_MISSING", "found": 0, "extracted": 0}
    extracted = extract_images_from_pdf(str(source))
    found = len(extracted)
    target_version_id = material_version_id or material.active_version_id
    # V7.5.1-04: Only delete images for the target version, not all versions.
    db.query(MaterialImage).filter(
        MaterialImage.material_id == material.id,
        MaterialImage.material_version_id == target_version_id,
    ).delete(synchronize_session=False)
    chunks = db.query(MaterialChunk).filter(
        MaterialChunk.material_id == material.id,
        MaterialChunk.is_active == 1,
    ).all()
    page_to_chunk = {}
    for chunk in chunks:
        if chunk.page_no:
            page_to_chunk.setdefault(chunk.page_no, chunk.id)
    image_dir = image_dir or ((Path(settings.UPLOAD_DIR) / material.file_path).parent / "images")
    image_dir.mkdir(parents=True, exist_ok=True)
    occurrences: set[tuple[int, str]] = set()
    count = 0
    for index, image in enumerate(extracted):
        bbox_json = json.dumps(list(getattr(image, "bbox", (0, 0, 0, 0))))
        occurrence = (image.page_no, bbox_json)
        if occurrence in occurrences:
            continue
        occurrences.add(occurrence)
        filename = f"page{image.page_no}_{index}.{image.format}"
        full_path = image_dir / filename
        full_path.write_bytes(image.image_bytes)
        db.add(MaterialImage(
            material_id=material.id, material_version_id=target_version_id,
            course_id=material.course_id, chunk_id=page_to_chunk.get(image.page_no), page_no=image.page_no,
            image_filename=filename, image_path=str(full_path.relative_to(Path(settings.UPLOAD_DIR))).replace("\\", "/"),
            width=image.width, height=image.height, format=image.format,
            is_decorative=1 if image.is_decorative else 0, decorative_reason=image.decorative_reason,
            perceptual_hash=image.perceptual_hash, color_variance=image.color_variance, coverage_ratio=image.coverage_ratio,
            sha256=hashlib.sha256(image.image_bytes).hexdigest(), xref=image.xref, bbox_json=bbox_json,
            render_status="ready",
        ))
        count += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return {"material_id": material.id, "status": "ready", "code": None, "found": found, "extracted": count}
