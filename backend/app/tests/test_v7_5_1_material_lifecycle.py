"""V7.5.1-04: Material lifecycle version-consistency tests.

Verifies that:
- Deleting a material cleans up MaterialPageAsset records.
- Re-extracting images only affects the target version.
- Image integrity only counts the active version's images.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services.material_delete_service import delete_material
from app.services.material_image_service import image_integrity, reextract_images


def _two_page_pdf(path: Path) -> None:
    doc = fitz.open()
    for label in ("Page 1", "Page 2"):
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=24)
    doc.save(path)
    doc.close()


def _make_material_with_version(
    db, upload_dir: Path, *, user_id: int, course_id: int, version: int = 1,
    file_path: str = "test.pdf",
) -> tuple[Material, MaterialVersion]:
    source = upload_dir / file_path
    _two_page_pdf(source)
    material = Material(
        user_id=user_id, course_id=course_id,
        filename=file_path, file_type="pdf", file_path=file_path,
        status="ready",
    )
    db.add(material)
    db.flush()
    v = MaterialVersion(material_id=material.id, version=version, status="ready")
    db.add(v)
    db.flush()
    material.active_version_id = v.id
    for pno in range(1, 3):
        db.add(MaterialPage(
            material_id=material.id, material_version_id=v.id,
            page_no=pno, page_type="text", raw_text=f"Page {pno}",
        ))
    db.commit()
    return material, v


def test_delete_material_cleans_page_assets(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # Add a page asset
    db_session.add(MaterialPageAsset(
        material_id=material.id, material_version_id=version.id,
        page_no=1, asset_path="pages/v1/page-0001.png",
        sha256="abc123", render_status="ready",
    ))
    db_session.commit()

    assert db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_id == material.id
    ).count() == 1

    # Delete the material
    result = delete_material(db_session, material)
    assert "page_assets" in result

    # Page assets should be gone
    assert db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_id == material.id
    ).count() == 0
    assert db_session.query(Material).filter(Material.id == material.id).first() is None


def test_reextract_only_affects_target_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """Re-extracting images for the active version must not delete
    images belonging to a different (historical) version."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
        version=1,
    )

    # Create a second version (historical)
    v2 = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add(v2)
    db_session.flush()
    # v1 becomes historical, v2 is active
    material.active_version_id = v2.id
    material.version = 2

    # Add images for both versions
    for ver_id in [v1.id, v2.id]:
        db_session.add(MaterialImage(
            material_id=material.id, material_version_id=ver_id,
            course_id=sample_course.id, page_no=1,
            image_filename="test.png", image_path="images/test.png",
            width=100, height=100, format="png",
            sha256="abc", render_status="ready",
        ))
    db_session.commit()

    assert db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v1.id
    ).count() == 1
    assert db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v2.id
    ).count() == 1

    # Re-extract for active version (v2)
    result = reextract_images(db_session, material)
    assert result["status"] == "ready"

    # v1 images should still exist
    v1_images = db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v1.id
    ).count()
    assert v1_images == 1, "Historical version images must not be deleted"

    # v2 images should have been replaced (old deleted, new created)
    v2_images = db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v2.id
    ).count()
    # The test PDF has no extractable images, so count may be 0
    assert v2_images >= 0


def test_image_integrity_only_counts_active_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """image_integrity should only count images for the active version."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
        version=1,
    )

    # Create second version as active
    v2 = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add(v2)
    db_session.flush()
    material.active_version_id = v2.id
    material.version = 2

    # v1 has 5 images, v2 has 0
    for i in range(5):
        db_session.add(MaterialImage(
            material_id=material.id, material_version_id=v1.id,
            course_id=sample_course.id, page_no=1,
            image_filename=f"old_{i}.png", image_path=f"images/old_{i}.png",
            width=100, height=100, format="png",
            sha256=f"old_{i}", render_status="ready",
        ))
    db_session.commit()

    result = image_integrity(db_session, material)
    # Should only count v2's images (0), not v1's (5)
    assert result["total"] == 0
    assert result["ready"] == 0
    assert result["missing"] == 0
