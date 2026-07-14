"""Regression coverage for assets-without-MaterialPage legacy PDFs."""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
from PIL import Image

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services.material_page_asset_service import backfill_missing_material_pages
from app.services.material_page_catalog_service import build_material_page_catalog


def _pdf(path: Path, count: int) -> None:
    doc = fitz.open()
    for number in range(count):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {number + 1}")
    doc.save(path)
    doc.close()


def _material(db, user, course, root: Path, count=3):
    _pdf(root / "legacy.pdf", count)
    material = Material(user_id=user.id, course_id=course.id, filename="legacy.pdf", file_type="pdf", file_path="legacy.pdf", status="ready")
    db.add(material); db.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db.add(version); db.flush(); material.active_version_id = version.id
    for number in range(1, count + 1):
        image_path = root / f"page-{number}.png"
        Image.new("RGB", (16, 16), "white").save(image_path)
        db.add(MaterialPageAsset(
            material_id=material.id, material_version_id=version.id, page_no=number,
            asset_path=image_path.name, sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(), render_status="ready",
        ))
    db.commit()
    return material


def test_catalog_returns_every_asset_backed_legacy_page_as_synthetic(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = _material(db_session, sample_user, sample_course, tmp_path)

    catalog = build_material_page_catalog(db_session, material)

    assert catalog["expected_pages"] == catalog["effective_pages"] == 3
    assert catalog["persisted_pages"] == 0
    assert catalog["synthetic_page_numbers"] == [1, 2, 3]
    assert [item["catalog_key"] for item in catalog["items"]] == [
        f"material:{material.id}:version:{material.active_version_id}:page:1",
        f"material:{material.id}:version:{material.active_version_id}:page:2",
        f"material:{material.id}:version:{material.active_version_id}:page:3",
    ]
    assert all(item["id"] is None and item["page_asset"] for item in catalog["items"])


def test_catalog_fills_pdf_gap_with_synthetic_page(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = _material(db_session, sample_user, sample_course, tmp_path)
    for number in (1, 3):
        db_session.add(MaterialPage(
            material_id=material.id, material_version_id=material.active_version_id,
            page_no=number, page_type="text", raw_text=f"page {number}",
        ))
    db_session.commit()

    catalog = build_material_page_catalog(db_session, material)

    assert [item["page_no"] for item in catalog["items"]] == [1, 2, 3]
    assert catalog["items"][1]["is_synthetic"] is True
    assert catalog["items"][1]["page_asset"]["id"] is not None


def test_backfill_is_idempotent_and_does_not_fabricate_ids(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = _material(db_session, sample_user, sample_course, tmp_path)
    first = backfill_missing_material_pages(db_session, material, page_numbers=[1, 2, 3])
    db_session.commit()
    second = backfill_missing_material_pages(db_session, material, page_numbers=[1, 2, 3])

    assert first == {"created": 3, "page_numbers": [1, 2, 3]}
    assert second == {"created": 0, "page_numbers": []}
    assert db_session.query(MaterialPage).filter(MaterialPage.material_id == material.id).count() == 3
