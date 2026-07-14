from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.services.material_parser import parse_with_retry


def _embedded_pdf(path: Path, *, label: str, color: str) -> None:
    image = Image.new("RGB", (320, 180), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 300, 160), outline="black", width=5)
    draw.text((40, 70), label, fill="black")
    payload = io.BytesIO()
    image.save(payload, format="PNG")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"{label} semantic text", fontsize=18)
    page.insert_image(fitz.Rect(72, 110, 392, 290), stream=payload.getvalue())
    doc.save(path)
    doc.close()


def _new_material(db, user_id: int, course_id: int, filename: str) -> Material:
    material = Material(
        user_id=user_id,
        course_id=course_id,
        filename=filename,
        file_type="pdf",
        file_path=filename,
        status="uploaded",
    )
    db.add(material)
    db.commit()
    return material


def test_full_reparse_binds_real_embedded_images_to_new_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "versioned.pdf"
    _embedded_pdf(source, label="version one", color="#fee2e2")
    material = _new_material(
        db_session, sample_user.id, sample_course.id, source.name
    )

    first_status, _ = parse_with_retry(
        db_session, material, sample_user.id, max_retries=1, sleep_fn=lambda _: None
    )
    db_session.refresh(material)
    v1_id = material.active_version_id
    v1_images = (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_version_id == v1_id)
        .all()
    )
    assert first_status == "ready"
    assert len(v1_images) >= 1
    v1_snapshot = {(row.id, row.image_path, row.sha256) for row in v1_images}
    assert all((tmp_path / row.image_path).is_file() for row in v1_images)

    _embedded_pdf(source, label="version two changed", color="#dcfce7")
    second_status, _ = parse_with_retry(
        db_session, material, sample_user.id, max_retries=1, sleep_fn=lambda _: None
    )
    db_session.refresh(material)
    v2_id = material.active_version_id
    assert second_status == "ready"
    assert v2_id != v1_id

    unchanged_v1 = (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_version_id == v1_id)
        .all()
    )
    v2_images = (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_version_id == v2_id)
        .all()
    )
    assert {(row.id, row.image_path, row.sha256) for row in unchanged_v1} == v1_snapshot
    assert len(v2_images) >= 1
    assert all("/images/v2/" in f"/{row.image_path}" for row in v2_images)

    v2_chunk_ids = {
        row.id
        for row in db_session.query(MaterialChunk)
        .filter(MaterialChunk.material_version_id == v2_id)
        .all()
    }
    assert v2_chunk_ids
    assert all(row.chunk_id is None or row.chunk_id in v2_chunk_ids for row in v2_images)
    assert (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_version_id.is_(None))
        .count()
        == 0
    )


def test_commit_failure_after_image_promotion_restores_v1(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "rollback.pdf"
    _embedded_pdf(source, label="stable v1", color="#dbeafe")
    material = _new_material(
        db_session, sample_user.id, sample_course.id, source.name
    )
    status, _ = parse_with_retry(
        db_session, material, sample_user.id, max_retries=1, sleep_fn=lambda _: None
    )
    assert status == "ready"
    db_session.refresh(material)
    v1_id = material.active_version_id
    v1_images = (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_version_id == v1_id)
        .all()
    )
    assert len(v1_images) >= 1
    v1_snapshot = {(row.id, row.image_path, row.sha256) for row in v1_images}

    _embedded_pdf(source, label="failing v2", color="#fef3c7")
    original_commit = db_session.commit
    failed = {"done": False}
    promoted_v2 = tmp_path / "images" / "v2"

    def fail_once_after_promotion():
        if promoted_v2.exists() and not failed["done"]:
            failed["done"] = True
            raise RuntimeError("simulated commit failure after image promotion")
        return original_commit()

    monkeypatch.setattr(db_session, "commit", fail_once_after_promotion)
    final_status, _ = parse_with_retry(
        db_session, material, sample_user.id, max_retries=1, sleep_fn=lambda _: None
    )
    monkeypatch.setattr(db_session, "commit", original_commit)

    current = db_session.query(Material).filter(Material.id == material.id).one()
    assert failed["done"] is True
    assert final_status == "ready"
    assert current.active_version_id == v1_id
    assert not promoted_v2.exists()
    assert (
        db_session.query(MaterialVersion)
        .filter(MaterialVersion.material_id == material.id, MaterialVersion.version == 2)
        .count()
        == 0
    )
    assert (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_id == material.id, MaterialImage.material_version_id != v1_id)
        .count()
        == 0
    )
    remaining_v1 = (
        db_session.query(MaterialImage)
        .filter(MaterialImage.material_version_id == v1_id)
        .all()
    )
    assert {(row.id, row.image_path, row.sha256) for row in remaining_v1} == v1_snapshot
