from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
from PIL import Image

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services import material_page_asset_service as service


def _png(color: tuple[int, int, int]) -> bytes:
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_promoting_journal_before_any_rename_keeps_old_readable_directory(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    """A crash after writing stage=promoting but before moving v1 is harmless.

    The DB and version directory both still describe the old manifest, backup
    does not exist, and staging contains the prospective new render. Recovery
    must keep v1 byte-for-byte and discard only staging/journal.
    """
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "old page")
    document.save(source)
    document.close()

    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="source.pdf",
        file_type="pdf",
        file_path="source.pdf",
        status="ready",
        version=1,
    )
    db_session.add(material)
    db_session.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db_session.add(version)
    db_session.flush()
    material.active_version_id = version.id
    db_session.add(
        MaterialPage(
            material_id=material.id,
            material_version_id=version.id,
            page_no=1,
            page_type="text",
            raw_text="old page",
        )
    )

    page_root = tmp_path / "pages"
    version_dir = page_root / "v1"
    staging_dir = page_root / ".staging"
    backup_dir = page_root / ".backup"
    version_dir.mkdir(parents=True)
    staging_dir.mkdir()
    old_bytes = _png((255, 0, 0))
    new_bytes = _png((0, 255, 0))
    (version_dir / "page-0001.png").write_bytes(old_bytes)
    (staging_dir / "page-0001.png").write_bytes(new_bytes)
    old_hash = hashlib.sha256(old_bytes).hexdigest()
    new_hash = hashlib.sha256(new_bytes).hexdigest()
    db_session.add(
        MaterialPageAsset(
            material_id=material.id,
            material_version_id=version.id,
            page_no=1,
            asset_path="pages/v1/page-0001.png",
            sha256=old_hash,
            render_status="ready",
        )
    )
    db_session.commit()

    journal = page_root / f".v7-journal-{material.id}-{version.id}-pre.json"
    service._write_journal(
        journal,
        material_id=material.id,
        version_id=version.id,
        stage="promoting",
        staging_dir=str(staging_dir),
        version_dir=str(version_dir),
        backup_dir=str(backup_dir),
        old_manifest=[{"page_no": 1, "filename": "page-0001.png", "sha256": old_hash}],
        new_manifest=[{"page_no": 1, "filename": "page-0001.png", "sha256": new_hash}],
    )

    lock = service._acquire_lock(material, version.id)
    assert lock is not None
    try:
        result = service._recover_incomplete_rebuild(
            db_session, material, page_root, version.id
        )
    finally:
        service._release_lock(lock)

    assert result is None
    assert (version_dir / "page-0001.png").read_bytes() == old_bytes
    assert not staging_dir.exists()
    assert not backup_dir.exists()
    assert not journal.exists()
