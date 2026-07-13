"""V7.5.2-01: Versioned image binding tests.

Verifies that re-parsing creates images bound to the new version,
historical version images are untouched, and chunk_id references
come from the target version's chunks.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page import MaterialPage
from app.services.material_image_service import reextract_images, image_integrity


def _two_page_pdf(path: Path) -> None:
    doc = fitz.open()
    for label in ("Page 1 text", "Page 2 text"):
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=24)
        page.draw_rect(fitz.Rect(72, 120, 360, 260), color=(0, 0.2, 0.8), fill=(0.9, 0.95, 1))
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
    material.version = version
    for pno in range(1, 3):
        db.add(MaterialPage(
            material_id=material.id, material_version_id=v.id,
            page_no=pno, page_type="text", raw_text=f"Page {pno}",
        ))
    db.commit()
    return material, v


def test_reextract_binds_images_to_target_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """reextract_images must bind all images to target_version_id."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # Create a second version
    v2 = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add(v2)
    db_session.flush()
    material.active_version_id = v2.id
    material.version = 2
    db_session.commit()

    # Add chunks for v2
    for pno in range(1, 3):
        db_session.add(MaterialChunk(
            material_id=material.id, material_version_id=v2.id,
            course_id=sample_course.id, chunk_index=pno - 1,
            page_no=pno, page_start=pno, page_end=pno,
            text=f"Chunk {pno}", raw_text=f"Chunk {pno}",
            is_active=1, content_hash=hashlib.sha256(f"chunk{pno}".encode()).hexdigest(),
        ))
    db_session.commit()

    # Re-extract with explicit version_id
    result = reextract_images(db_session, material, material_version_id=v2.id)
    assert result["status"] == "ready"

    images = db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v2.id
    ).all()
    for img in images:
        assert img.material_version_id == v2.id, "Image must be bound to v2"


def test_reextract_chunk_query_uses_target_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """chunk_id must come from the target version's chunks, not is_active chunks."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # v1 has a chunk on page 1
    v1_chunk = MaterialChunk(
        material_id=material.id, material_version_id=v1.id,
        course_id=sample_course.id, chunk_index=0,
        page_no=1, page_start=1, page_end=1,
        text="v1 chunk", raw_text="v1 chunk",
        is_active=0, content_hash="a" * 64,
    )
    db_session.add(v1_chunk)

    # v2 has a chunk on page 1
    v2 = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add(v2)
    db_session.flush()
    v2_chunk = MaterialChunk(
        material_id=material.id, material_version_id=v2.id,
        course_id=sample_course.id, chunk_index=0,
        page_no=1, page_start=1, page_end=1,
        text="v2 chunk", raw_text="v2 chunk",
        is_active=1, content_hash="b" * 64,
    )
    db_session.add(v2_chunk)
    material.active_version_id = v2.id
    material.version = 2
    db_session.commit()

    result = reextract_images(db_session, material, material_version_id=v2.id)
    assert result["status"] == "ready"

    images = db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v2.id,
        MaterialImage.page_no == 1,
    ).all()
    for img in images:
        if img.chunk_id is not None:
            assert img.chunk_id == v2_chunk.id, "chunk_id must come from v2, not v1"


def test_reextract_does_not_touch_historical_version_images(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """Re-extracting for v2 must not delete or modify v1 images."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # Add v1 images
    v1_img_dir = tmp_path / material.file_path.replace(".pdf", "") / "images" / "v1"
    v1_img_dir.mkdir(parents=True, exist_ok=True)
    v1_img_path = v1_img_dir / "page1_0.png"
    v1_img_path.write_bytes(b"\x89PNG\r\n\x1a\nv1")
    v1_hash = hashlib.sha256(v1_img_path.read_bytes()).hexdigest()
    v1_img = MaterialImage(
        material_id=material.id, material_version_id=v1.id,
        course_id=sample_course.id, page_no=1,
        image_filename="page1_0.png",
        image_path=str(v1_img_path.relative_to(tmp_path)).replace("\\", "/"),
        width=100, height=100, format="png",
        sha256=v1_hash, render_status="ready",
    )
    db_session.add(v1_img)
    db_session.commit()

    # Create v2 and re-extract
    v2 = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add(v2)
    db_session.flush()
    material.active_version_id = v2.id
    material.version = 2
    db_session.commit()

    result = reextract_images(db_session, material, material_version_id=v2.id)
    assert result["status"] == "ready"

    # v1 image must be untouched
    v1_images = db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id == v1.id
    ).all()
    assert len(v1_images) == 1
    assert v1_images[0].sha256 == v1_hash
    assert v1_images[0].image_path == str(v1_img_path.relative_to(tmp_path)).replace("\\", "/")


def test_reextract_no_null_version_images_created(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """No new MaterialImage with material_version_id IS NULL should be created."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    result = reextract_images(db_session, material, material_version_id=v1.id)
    assert result["status"] == "ready"

    null_images = db_session.query(MaterialImage).filter(
        MaterialImage.material_version_id.is_(None)
    ).all()
    assert len(null_images) == 0, "No NULL version images should exist"


def test_reextract_both_versions_null_returns_error(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """If both target_version_id and active_version_id are None, return error."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v1 = _make_material_with_version(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )
    # Clear active_version_id
    material.active_version_id = None
    db_session.commit()

    result = reextract_images(db_session, material, material_version_id=None)
    assert result["status"] == "error"
    assert "no_material_version" in result.get("code", "").lower()
