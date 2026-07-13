"""Production-path regression coverage for page-level visual fidelity."""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from app.core import database
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.models.material_image import MaterialImage
from app.retrieval.image_extractor import ImageInfo
from app.retrieval.page_renderer import render_pdf_pages
from app.retrieval.pdf_layout_parser import annotate_pdf_layout
from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk_document
from app.services.material_image_service import image_integrity, reextract_images
from app.services.material_parser import parse_with_retry


def _two_page_pdf(path: Path) -> None:
    document = fitz.open()
    for label in ("Cover visual", "Network diagram -> layers"):
        page = document.new_page()
        page.insert_text((72, 72), label, fontsize=24)
        page.draw_rect(fitz.Rect(72, 120, 360, 260), color=(0, 0.2, 0.8), fill=(0.9, 0.95, 1))
    document.save(path)
    document.close()


def test_pdf_page_renderer_covers_every_page_and_emits_decodable_pngs(tmp_path: Path) -> None:
    source = tmp_path / "vector-slides.pdf"
    _two_page_pdf(source)

    assets = render_pdf_pages(source, tmp_path / "pages", dpi=144)

    assert [asset.page_no for asset in assets] == [1, 2]
    assert all(asset.width > 500 and asset.height > 500 for asset in assets)
    assert all(len(asset.sha256) == 64 for asset in assets)
    for asset in assets:
        payload = (tmp_path / "pages" / asset.filename).read_bytes()
        assert payload.startswith(b"\x89PNG")
        assert hashlib.sha256(payload).hexdigest() == asset.sha256


def test_page_asset_api_is_version_scoped_and_user_isolated(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    for username in ("alice", "bob"):
        client.post("/api/v1/auth/register", json={"username": username, "password": "secret123", "email": f"{username}@example.test"})
    alice_token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "secret123"}).json()["access_token"]
    bob_token = client.post("/api/v1/auth/login", json={"username": "bob", "password": "secret123"}).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}
    course_id = client.post("/api/v1/courses", json={"name": "Networks"}, headers=alice_headers).json()["id"]
    material_id = client.post(f"/api/v1/courses/{course_id}/materials", files={"file": ("slides.pdf", b"%PDF", "application/pdf")}, headers=alice_headers).json()["id"]
    output = tmp_path / "1" / str(course_id) / str(material_id) / "pages" / "v1"
    output.mkdir(parents=True)
    png = output / "page-0001-test.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    db = database.SessionLocal()
    try:
        material = db.get(Material, material_id)
        version = MaterialVersion(material_id=material.id, version=1, status="ready")
        db.add(version)
        db.flush()
        material.active_version_id = version.id
        material.status = "ready"
        page = MaterialPage(material_id=material.id, material_version_id=version.id, page_no=1, raw_text="visual page")
        asset = MaterialPageAsset(material_id=material.id, material_version_id=version.id, page_no=1, asset_path=str(png.relative_to(tmp_path)).replace("\\", "/"), width=100, height=100, dpi=144, sha256=digest, render_status="ready")
        db.add_all([page, asset])
        db.commit()
        asset_id = asset.id
    finally:
        db.close()

    catalogue = client.get(f"/api/v1/materials/{material_id}/pages", headers=alice_headers)
    assert catalogue.status_code == 200
    assert catalogue.json()["items"][0]["page_asset"]["id"] == asset_id
    assert client.get(f"/api/v1/materials/page-assets/{asset_id}/file", headers=bob_headers).status_code == 404
    response = client.get(f"/api/v1/materials/page-assets/{asset_id}/file", headers=alice_headers)
    assert response.status_code == 200
    assert response.headers["etag"] == f'"{digest}"'


def test_broken_embedded_image_uses_ready_page_fallback(db_session, sample_user, sample_course, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="slides.pdf", file_type="pdf", file_path="slides.pdf", status="ready")
    db_session.add(material)
    db_session.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db_session.add(version)
    db_session.flush()
    material.active_version_id = version.id
    source = tmp_path / "fallback.pdf"
    _two_page_pdf(source)
    page_dir = tmp_path / "pages"
    rendered = render_pdf_pages(source, page_dir)[0]
    page_path = page_dir / rendered.filename
    db_session.add_all([
        MaterialPageAsset(material_id=material.id, material_version_id=version.id, page_no=1, asset_path=f"pages/{rendered.filename}", sha256=rendered.sha256, render_status="ready"),
        MaterialImage(material_id=material.id, material_version_id=version.id, course_id=sample_course.id, page_no=1, image_filename="bad.png", image_path="missing/bad.png", format="png"),
    ])
    db_session.commit()

    result = image_integrity(db_session, material)
    assert result["status"] == "page_fallback_ready"
    assert result["missing"] == 1
    assert result["page_assets_ready"] == 1


def test_reextract_keeps_same_embedded_image_on_different_page_occurrences(db_session, sample_user, sample_course, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "slides.pdf"
    source.write_bytes(b"fixture")
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="slides.pdf", file_type="pdf", file_path="slides.pdf", status="ready")
    db_session.add(material)
    db_session.commit()
    payload = b"same-bitmap"
    occurrences = [
        ImageInfo(page_no=1, image_bytes=payload, width=100, height=100, xref=7, bbox=(1, 1, 50, 50)),
        ImageInfo(page_no=2, image_bytes=payload, width=100, height=100, xref=7, bbox=(2, 2, 51, 51)),
    ]
    monkeypatch.setattr("app.retrieval.image_extractor.extract_images_from_pdf", lambda _: occurrences)

    result = reextract_images(db_session, material, image_dir=tmp_path / "images")
    rows = db_session.query(MaterialImage).filter_by(material_id=material.id).order_by(MaterialImage.page_no).all()
    assert result["extracted"] == 2
    assert [row.page_no for row in rows] == [1, 2]
    assert len({row.bbox_json for row in rows}) == 2


def test_diagram_like_page_becomes_a_visual_summary_not_flattened_text() -> None:
    blocks = [
        DocumentBlock(block_id=f"b{index}", page_no=9, block_type="body", reading_order=index,
                      text=label, bbox=(20 + (index % 4) * 120, 30 + (index // 4) * 100, 100, 50))
        for index, label in enumerate(["链路层", "网络层", "物理层", "TCP", "IP", "Router", "Host", "Switch"])
    ]
    page = DocumentPage(page_no=9, page_type="pdf", blocks=blocks)

    annotate_pdf_layout([page])
    chunks = semantic_chunk_document([page])

    assert page.layout_uncertain is True
    assert chunks[0]["split_reason"] == "visual_page_summary"
    assert chunks[0]["is_indexable"] is False
    assert "原页视觉资产" in chunks[0]["text"]


def test_real_pdf_parse_activates_complete_versioned_page_assets(db_session, sample_user, sample_course, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "course-ppt.pdf"
    _two_page_pdf(source)
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename=source.name, file_type="pdf", file_path=source.name, status="uploaded")
    db_session.add(material)
    db_session.commit()

    status, _ = parse_with_retry(db_session, material, sample_user.id, sleep_fn=lambda _: None)
    db_session.refresh(material)
    assets = db_session.query(MaterialPageAsset).filter_by(material_version_id=material.active_version_id).order_by(MaterialPageAsset.page_no).all()

    assert status == material.status == "ready"
    assert [asset.page_no for asset in assets] == [1, 2]
    assert all(asset.render_status == "ready" for asset in assets)
    assert all((tmp_path / asset.asset_path).read_bytes().startswith(b"\x89PNG") for asset in assets)
    assert image_integrity(db_session, material)["page_assets_ready"] == 2
