"""V7.5.2-02: Page asset integrity based on actual page coverage.

Verifies that expected_pages comes from MaterialPage.page_no set or PDF
page count, not from len(assets). Missing, duplicate, and corrupt pages
are detected by page-number set difference.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest
from PIL import Image

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services.material_page_asset_service import evaluate_page_asset_coverage


def _valid_png(width=100, height=100, color=(255, 0, 0)) -> bytes:
    import io
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _corrupt_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _make_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i+1}", fontsize=24)
    doc.save(path)
    doc.close()


def _setup_material(db, upload_dir, *, user_id, course_id, num_pages=3, file_path="test.pdf"):
    source = upload_dir / file_path
    _make_pdf(source, num_pages)
    material = Material(
        user_id=user_id, course_id=course_id,
        filename=file_path, file_type="pdf", file_path=file_path,
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


def _add_page_asset(db, material, version_id, page_no, *, content=None, sha256_hash=None, upload_dir=None, status="ready"):
    if content is None:
        content = _valid_png()
    if sha256_hash is None:
        sha256_hash = hashlib.sha256(content).hexdigest()
    asset_dir = Path(settings.UPLOAD_DIR) / f"pages_test/{material.id}/v1"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_file = asset_dir / f"page-{page_no:04d}.png"
    asset_file.write_bytes(content)
    rel_path = str(asset_file.relative_to(Path(settings.UPLOAD_DIR))).replace("\\", "/")
    db.add(MaterialPageAsset(
        material_id=material.id, material_version_id=version_id,
        page_no=page_no, asset_path=rel_path,
        sha256=sha256_hash, render_status=status,
    ))
    db.commit()


def test_full_coverage_returns_ready(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id, num_pages=3
    )
    for pno in range(1, 4):
        _add_page_asset(db_session, material, v.id, pno)

    result = evaluate_page_asset_coverage(db_session, material)
    assert result["status"] == "ready"
    assert result["expected_pages"] == 3
    assert result["ready_pages"] == 3
    assert result["missing_pages"] == 0
    assert result["missing_page_numbers"] == []


def test_missing_last_page_returns_partial(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id, num_pages=3
    )
    _add_page_asset(db_session, material, v.id, 1)
    _add_page_asset(db_session, material, v.id, 2)
    # Page 3 missing

    result = evaluate_page_asset_coverage(db_session, material)
    assert result["status"] == "partial"
    assert result["expected_pages"] == 3
    assert result["ready_pages"] == 2
    assert result["missing_pages"] == 1
    assert result["missing_page_numbers"] == [3]


def test_corrupt_page_not_ready(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id, num_pages=2
    )
    _add_page_asset(db_session, material, v.id, 1)
    _add_page_asset(db_session, material, v.id, 2, content=_corrupt_png())

    result = evaluate_page_asset_coverage(db_session, material)
    assert result["status"] == "partial"
    assert result["ready_pages"] == 1
    assert 2 in result["invalid_page_numbers"]


def test_hash_mismatch_not_ready(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id, num_pages=2
    )
    _add_page_asset(db_session, material, v.id, 1)
    _add_page_asset(db_session, material, v.id, 2, sha256_hash="0" * 64)

    result = evaluate_page_asset_coverage(db_session, material)
    assert result["status"] == "partial"
    assert result["ready_pages"] == 1


def test_duplicate_page_numbers_detected(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """DB UNIQUE constraint prevents duplicates at the schema level.
    The evaluate function has defensive duplicate detection, but it
    cannot be triggered through normal ORM operations."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id, num_pages=2
    )
    _add_page_asset(db_session, material, v.id, 1)
    _add_page_asset(db_session, material, v.id, 2)

    # Verify no duplicates exist (constraint enforced)
    from sqlalchemy import text
    result = db_session.execute(text(
        "SELECT page_no, COUNT(*) as cnt FROM material_page_assets "
        "WHERE material_version_id = :vid GROUP BY page_no HAVING cnt > 1"
    ), {"vid": v.id}).fetchall()
    assert len(result) == 0, "DB constraint should prevent duplicates"

    # Coverage should be ready with no duplicates
    cov = evaluate_page_asset_coverage(db_session, material)
    assert cov["status"] == "ready"
    assert cov["duplicate_page_numbers"] == []


def test_extra_page_does_not_change_expected(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id, num_pages=2
    )
    _add_page_asset(db_session, material, v.id, 1)
    _add_page_asset(db_session, material, v.id, 2)
    _add_page_asset(db_session, material, v.id, 3)  # extra page

    result = evaluate_page_asset_coverage(db_session, material)
    assert result["expected_pages"] == 2  # not 3
    assert 3 in result.get("extra_page_numbers", [])


def test_no_material_page_uses_pdf_page_count(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """Old materials without MaterialPage should use PDF page count."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "legacy.pdf"
    _make_pdf(source, 3)
    material = Material(
        user_id=sample_user.id, course_id=sample_course.id,
        filename="legacy.pdf", file_type="pdf", file_path="legacy.pdf",
        status="ready",
    )
    db_session.add(material)
    db_session.flush()
    v = MaterialVersion(material_id=material.id, version=1, status="ready")
    db_session.add(v)
    db_session.flush()
    material.active_version_id = v.id
    material.version = 1
    # No MaterialPage records
    db_session.commit()

    result = evaluate_page_asset_coverage(db_session, material)
    assert result["expected_pages"] == 3  # from PDF
    assert result["status"] == "missing"
    assert result["missing_page_numbers"] == [1, 2, 3]
