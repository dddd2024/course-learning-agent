"""V7.5.2-06: Page-asset edge-case tests.

Verifies that page-asset coverage evaluation handles corrupted page
images, NULL-version images, single-page load failures, NULL page-asset
fields, and missing on-disk files gracefully.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.course import Course
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.models.user import User
from app.services.material_page_asset_service import evaluate_page_asset_coverage
from app.services.material_image_service import reextract_images


# ── helpers ─────────────────────────────────────────────────────────

def _valid_png(color=(255, 0, 0)) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color).save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i+1}", fontsize=24)
    doc.save(path)
    doc.close()


def _make_material(db, *, user_id, course_id, num_pages=1):
    """Create a material with an active version and the given number of pages.

    Returns ``(material, version)``.
    """
    material = Material(
        user_id=user_id, course_id=course_id,
        filename="test.pdf", file_type="pdf", file_path="test.pdf",
        status="ready",
    )
    db.add(material)
    db.flush()
    v = MaterialVersion(material_id=material.id, version=1, status="ready")
    db.add(v)
    db.flush()
    material.active_version_id = v.id
    material.version = 1
    for pno in range(1, num_pages + 1):
        db.add(MaterialPage(
            material_id=material.id, material_version_id=v.id,
            page_no=pno, page_type="text", raw_text=f"Page {pno}",
        ))
    db.commit()
    return material, v


# ── V7.5.2-06 edge cases ────────────────────────────────────────────

def test_corrupted_page_asset_returns_failed_status(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """A page asset with render_status='failed' must not be counted as ready."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _make_material(
        db_session, user_id=sample_user.id, course_id=sample_course.id, num_pages=1,
    )
    # Simulate a corrupted / failed-render page asset
    db_session.add(MaterialPageAsset(
        material_id=material.id, material_version_id=v.id,
        page_no=1, asset_path="pages/v1/page-0001.png",
        render_status="failed",
    ))
    db_session.commit()

    cov = evaluate_page_asset_coverage(db_session, material)
    assert cov["expected_pages"] == 1
    assert cov["ready_pages"] == 0
    assert 1 in cov["missing_page_numbers"]


def test_null_version_id_image_returns_error(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """reextract_images must return status='error' / code='NO_MATERIAL_VERSION'
    when the material has no active version."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    # A real PDF file must exist so reextract_images passes the file-exists
    # guard before reaching the version-id check.
    source = tmp_path / "test.pdf"
    _make_pdf(source, pages=1)
    material = Material(
        user_id=sample_user.id, course_id=sample_course.id,
        filename="test.pdf", file_type="pdf", file_path="test.pdf",
        status="ready", active_version_id=None,
    )
    db_session.add(material)
    db_session.commit()

    result = reextract_images(db_session, material)
    assert result["status"] == "error"
    assert result["code"] == "NO_MATERIAL_VERSION"


def test_single_page_failure_does_not_block_others(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """A single failed page must not prevent other ready pages from being counted.

    Three pages: pages 1 and 2 have valid ready assets, page 3 has a failed
    render.  Coverage must report expected_pages=3, ready_pages=2.
    """
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _make_material(
        db_session, user_id=sample_user.id, course_id=sample_course.id, num_pages=3,
    )
    # Create valid PNG files for pages 1 and 2
    asset_dir = tmp_path / "pages" / "v1"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for pno in (1, 2):
        content = _valid_png(color=(pno * 50, 0, 0))
        asset_file = asset_dir / f"page-{pno:04d}.png"
        asset_file.write_bytes(content)
        rel_path = str(asset_file.relative_to(tmp_path)).replace("\\", "/")
        db_session.add(MaterialPageAsset(
            material_id=material.id, material_version_id=v.id,
            page_no=pno, asset_path=rel_path,
            sha256=hashlib.sha256(content).hexdigest(),
            render_status="ready",
        ))
    # Page 3 has a failed render
    db_session.add(MaterialPageAsset(
        material_id=material.id, material_version_id=v.id,
        page_no=3, asset_path="pages/v1/page-0003.png",
        render_status="failed",
    ))
    db_session.commit()

    cov = evaluate_page_asset_coverage(db_session, material)
    assert cov["expected_pages"] == 3
    assert cov["ready_pages"] == 2
    assert 3 in cov["missing_page_numbers"]


def test_page_asset_with_null_page_asset_field(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """A MaterialPage with no associated asset must be counted in expected
    but not in ready."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _make_material(
        db_session, user_id=sample_user.id, course_id=sample_course.id, num_pages=1,
    )
    # No MaterialPageAsset created — the page exists but has no asset

    cov = evaluate_page_asset_coverage(db_session, material)
    assert cov["expected_pages"] == 1
    assert cov["ready_pages"] == 0
    assert 1 in cov["missing_page_numbers"]


def test_empty_blob_validation(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """A page asset whose file is missing on disk must be tracked correctly.

    The asset claims render_status='ready' but its asset_path points to a
    file that does not exist.  evaluate_page_asset_coverage must handle
    this gracefully (no crash) and report the page as not ready.
    """
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _make_material(
        db_session, user_id=sample_user.id, course_id=sample_course.id, num_pages=1,
    )
    db_session.add(MaterialPageAsset(
        material_id=material.id, material_version_id=v.id,
        page_no=1, asset_path="pages/v1/page-0001.png",
        render_status="ready",
    ))
    db_session.commit()

    cov = evaluate_page_asset_coverage(db_session, material)
    assert cov["expected_pages"] == 1
    assert cov["ready_pages"] == 0
    assert 1 in cov["missing_page_numbers"]
