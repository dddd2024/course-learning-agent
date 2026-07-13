"""V7.5.1-01: Page-asset backfill for legacy PDFs that predate page rendering."""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services.material_page_asset_service import ensure_active_page_assets
from app.services.material_parser import parse_with_retry


def _three_page_pdf(path: Path) -> None:
    """Create a real 3-page PDF fixture with text and vector graphics."""
    doc = fitz.open()
    for label in ("第一章 概述", "第二章 原理", "第三章 应用"):
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=24)
        page.draw_rect(fitz.Rect(72, 120, 360, 260), color=(0, 0.2, 0.8), fill=(0.9, 0.95, 1))
    doc.save(path)
    doc.close()


def _legacy_material_with_pages(
    db: Session, upload_dir: Path, *, user_id: int = 1, course_id: int = 1,
    file_path: str = "legacy.pdf",
) -> Material:
    """Create a ready material that has MaterialPage rows but no page assets.

    Simulates a V7.5.0-prior PDF that was parsed before page rendering
    was introduced.
    """
    source = upload_dir / file_path
    _three_page_pdf(source)
    material = Material(
        user_id=user_id,
        course_id=course_id,
        filename=file_path,
        file_type="pdf",
        file_path=file_path,
        status="ready",
    )
    db.add(material)
    db.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db.add(version)
    db.flush()
    material.active_version_id = version.id
    # Simulate pre-page-asset parse: pages exist, assets do not.
    for page_no in range(1, 4):
        db.add(
            MaterialPage(
                material_id=material.id,
                material_version_id=version.id,
                page_no=page_no,
                page_type="text",
                raw_text=f"Page {page_no} text",
            )
        )
    db.commit()
    return material


def test_backfill_creates_page_assets_for_legacy_pdf(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = _legacy_material_with_pages(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    result = ensure_active_page_assets(db_session, material)
    assert result["status"] == "ready"
    assert result["expected_pages"] == 3
    assert result["ready_pages"] == 3
    assert result["missing_pages"] == 0

    assets = (
        db_session.query(MaterialPageAsset)
        .filter(MaterialPageAsset.material_version_id == material.active_version_id)
        .order_by(MaterialPageAsset.page_no)
        .all()
    )
    assert [a.page_no for a in assets] == [1, 2, 3]
    assert all(a.render_status == "ready" for a in assets)
    assert all((tmp_path / a.asset_path).read_bytes().startswith(b"\x89PNG") for a in assets)


def test_backfill_is_idempotent(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = _legacy_material_with_pages(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # First backfill
    result1 = ensure_active_page_assets(db_session, material)
    assert result1["ready_pages"] == 3
    asset_count_1 = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == material.active_version_id
    ).count()

    # Second backfill — should not create duplicates
    result2 = ensure_active_page_assets(db_session, material)
    assert result2["ready_pages"] == 3
    asset_count_2 = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == material.active_version_id
    ).count()
    assert asset_count_1 == asset_count_2 == 3


def test_backfill_preserves_old_data_on_failure(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = _legacy_material_with_pages(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # Create a pre-existing valid page asset that should survive a failure
    version_id = material.active_version_id
    old_asset_dir = tmp_path / "pages" / "old"
    old_asset_dir.mkdir(parents=True)
    old_png = old_asset_dir / "page-0001-old.png"
    old_png.write_bytes(b"\x89PNG\r\n\x1a\nold")
    old_digest = hashlib.sha256(old_png.read_bytes()).hexdigest()
    db_session.add(
        MaterialPageAsset(
            material_id=material.id,
            material_version_id=version_id,
            page_no=1,
            asset_path=str(old_png.relative_to(tmp_path)).replace("\\", "/"),
            sha256=old_digest,
            render_status="ready",
        )
    )
    db_session.commit()

    # Simulate render failure
    def failing_render(*args, **kwargs):
        raise RuntimeError("simulated render failure")

    monkeypatch.setattr("app.services.material_page_asset_service.render_pdf_pages", failing_render)

    result = ensure_active_page_assets(db_session, material)
    assert result["status"] in {"partial", "missing"}
    # The old asset for page 1 should still be there
    remaining = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == version_id,
        MaterialPageAsset.page_no == 1,
    ).all()
    assert len(remaining) == 1
    assert remaining[0].sha256 == old_digest


def test_rebuild_endpoint_returns_page_counts(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    # Register and login
    client.post("/api/v1/auth/register", json={"username": "tester", "password": "secret123", "email": "t@example.com"})
    token = client.post("/api/v1/auth/login", json={"username": "tester", "password": "secret123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    course_id = client.post("/api/v1/courses", json={"name": "Test"}, headers=headers).json()["id"]

    # Upload a real PDF
    source = tmp_path / "legacy.pdf"
    _three_page_pdf(source)
    with open(source, "rb") as f:
        material_id = client.post(
            f"/api/v1/courses/{course_id}/materials",
            files={"file": ("legacy.pdf", f, "application/pdf")},
            headers=headers,
        ).json()["id"]

    # Set up legacy state directly in DB via the patched SessionLocal
    from app.core.database import SessionLocal
    from app.models.material import Material as Mat, MaterialVersion as MV
    from app.models.material_page import MaterialPage as MP

    db = SessionLocal()
    try:
        mat = db.query(Mat).filter(Mat.id == material_id).first()
        v = MV(material_id=mat.id, version=1, status="ready")
        db.add(v)
        db.flush()
        mat.active_version_id = v.id
        mat.status = "ready"
        for pno in range(1, 4):
            db.add(MP(material_id=mat.id, material_version_id=v.id, page_no=pno, page_type="text", raw_text=f"p{pno}"))
        db.commit()
    finally:
        db.close()

    # Call rebuild endpoint
    resp = client.post(f"/api/v1/materials/{material_id}/page-assets/rebuild", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["expected_pages"] == 3
    assert data["ready_pages"] == 3
    assert data["missing_pages"] == 0
    assert data["status"] == "ready"


def test_parse_reuse_version_backfills_missing_page_assets(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """Re-parsing a PDF whose content_hash matches an existing version
    must still ensure page assets are present (V7.5.1-01 core fix)."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "reuse.pdf"
    _three_page_pdf(source)

    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="reuse.pdf",
        file_type="pdf",
        file_path="reuse.pdf",
        status="uploaded",
    )
    db_session.add(material)
    db_session.commit()

    # First parse: creates version with page assets
    status, _ = parse_with_retry(db_session, material, sample_user.id, sleep_fn=lambda _: None)
    assert status == "ready"
    assets_before = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == material.active_version_id
    ).count()
    assert assets_before == 3

    # Simulate legacy: delete all page assets
    db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == material.active_version_id
    ).delete(synchronize_session=False)
    db_session.commit()
    material.status = "ready"
    db_session.commit()

    # Re-parse: same content_hash → existing version reuse path
    # Page assets should be backfilled
    status2, _ = parse_with_retry(db_session, material, sample_user.id, sleep_fn=lambda _: None)
    assert status2 == "ready"
    assets_after = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == material.active_version_id
    ).count()
    assert assets_after == 3
