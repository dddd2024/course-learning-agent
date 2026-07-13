import io
from pathlib import Path

from PIL import Image

from app.models.material import Material
from app.models.material_image import MaterialImage
from app.services.material_image_service import image_integrity, image_state


def test_missing_image_is_reported_without_hiding_material(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="a.pdf", file_type="pdf", file_path="a/original.pdf", status="ready")
    db_session.add(material); db_session.flush()
    image = MaterialImage(material_id=material.id, course_id=sample_course.id, page_no=1, image_filename="missing.png", image_path="a/images/missing.png")
    db_session.add(image); db_session.commit()
    assert image_state(image) == ("missing", "MATERIAL_IMAGE_FILE_MISSING")
    assert image_integrity(db_session, material)["missing"] == 1
    assert material.status == "ready"


def test_ready_image_integrity_uses_upload_root(db_session, sample_user, sample_course, tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    (tmp_path / "a/images").mkdir(parents=True)
    payload = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(payload, format="PNG")
    (tmp_path / "a/images/p.png").write_bytes(payload.getvalue())
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="a.pdf", file_type="pdf", file_path="a/original.pdf", status="ready")
    db_session.add(material); db_session.flush()
    image = MaterialImage(material_id=material.id, course_id=sample_course.id, page_no=1, image_filename="p.png", image_path="a/images/p.png")
    db_session.add(image); db_session.commit()
    assert image_integrity(db_session, material)["status"] == "ready"
