from __future__ import annotations

import hashlib
import io

from PIL import Image

from app.api.v1.endpoints.parse import list_chunks
from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (20, 100, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_chunk_reader_exposes_only_ready_images_from_active_version(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="view.pdf",
        file_type="pdf",
        file_path="view.pdf",
        status="ready",
        version=2,
    )
    db_session.add(material)
    db_session.flush()
    v1 = MaterialVersion(material_id=material.id, version=1, status="ready")
    v2 = MaterialVersion(material_id=material.id, version=2, status="ready")
    db_session.add_all([v1, v2])
    db_session.flush()
    material.active_version_id = v2.id

    chunk = MaterialChunk(
        material_id=material.id,
        material_version_id=v2.id,
        course_id=sample_course.id,
        chunk_index=0,
        page_no=1,
        page_start=1,
        page_end=1,
        text="active chunk",
        raw_text="active chunk",
        content_hash="a" * 64,
        is_active=1,
    )
    db_session.add(chunk)
    db_session.flush()

    payload = _png()
    ready_path = tmp_path / "images" / "active.png"
    ready_path.parent.mkdir(parents=True)
    ready_path.write_bytes(payload)

    def image(version_id, status, name, chunk_id=None):
        return MaterialImage(
            material_id=material.id,
            material_version_id=version_id,
            course_id=sample_course.id,
            chunk_id=chunk_id,
            page_no=1,
            image_filename=name,
            image_path="images/active.png",
            width=64,
            height=64,
            format="png",
            sha256=hashlib.sha256(payload).hexdigest(),
            render_status=status,
            is_decorative=0,
        )

    active_ready = image(v2.id, "ready", "active.png", chunk.id)
    db_session.add_all(
        [
            active_ready,
            image(v1.id, "ready", "historical.png", chunk.id),
            image(None, "ready", "legacy-null.png", chunk.id),
            image(v2.id, "quarantined", "quarantined.png", chunk.id),
        ]
    )
    db_session.commit()

    response = list_chunks(
        material.id,
        page=1,
        page_size=10,
        include_decorative=False,
        db=db_session,
        current_user=sample_user,
    )

    assert response.total == 1
    assert len(response.items) == 1
    assert [row.id for row in response.items[0].images] == [active_ready.id]
