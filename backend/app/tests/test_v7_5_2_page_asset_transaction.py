"""V7.5.2-03: Page-asset rebuild compensation transaction tests.

Verifies that rebuild survives failures at every stage and always
leaves the old readable version intact.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from app.core.config import settings
from app.models.material import Material, MaterialVersion
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services.material_page_asset_service import rebuild_page_assets
from app.services.material_page_asset_service import evaluate_page_asset_coverage


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


def _setup_material(db, upload_dir, *, user_id, course_id, num_pages=3):
    source = upload_dir / "test.pdf"
    _make_pdf(source, num_pages)
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
    # Add existing valid page assets at the path rebuild expects:
    # (UPLOAD_DIR / file_path).parent / "pages" / "v{version}"
    asset_dir = upload_dir / "pages" / "v1"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for pno in range(1, num_pages + 1):
        content = _valid_png(color=(pno * 50, 0, 0))
        asset_file = asset_dir / f"page-{pno:04d}.png"
        asset_file.write_bytes(content)
        rel_path = str(asset_file.relative_to(upload_dir)).replace("\\", "/")
        db.add(MaterialPageAsset(
            material_id=material.id, material_version_id=v.id,
            page_no=pno, asset_path=rel_path,
            sha256=hashlib.sha256(content).hexdigest(),
            render_status="ready",
        ))
    db.commit()
    return material, v


def test_rebuild_succeeds_normally(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )
    result = rebuild_page_assets(db_session, material)
    assert result["status"] == "ready"
    assert result["ready_pages"] == 3
    cov = evaluate_page_asset_coverage(db_session, material)
    assert cov["status"] == "ready"


def test_rebuild_render_failure_preserves_old(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )
    old_assets = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == v.id
    ).all()
    old_hashes = {a.sha256 for a in old_assets}

    # Make render fail
    def failing_render(*args, **kwargs):
        raise RuntimeError("simulated render failure")

    monkeypatch.setattr("app.services.material_page_asset_service.render_pdf_pages", failing_render)
    result = rebuild_page_assets(db_session, material)
    # Rebuild failed but old assets are still valid, so status may be "ready"
    # The key assertion is that old assets are preserved

    # Old assets must be intact
    current_assets = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == v.id
    ).all()
    assert {a.sha256 for a in current_assets} == old_hashes
    # Old files must still exist
    for a in current_assets:
        assert (tmp_path / a.asset_path).is_file()


def test_rebuild_db_commit_failure_restores_old_dir(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    """If DB commit fails after file promotion, old files must be restored."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )
    old_paths = [
        a.asset_path for a in db_session.query(MaterialPageAsset).filter(
            MaterialPageAsset.material_version_id == v.id
        ).all()
    ]

    # Patch Session.commit at the class level. The monkeypatch is applied
    # AFTER _setup_material's commit, so the first call through the patch
    # is the one inside _do_rebuild.
    from sqlalchemy.orm import Session as SASession
    original_commit = SASession.commit

    def failing_commit(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(SASession, "commit", failing_commit)
    result = rebuild_page_assets(db_session, material)
    # Restore commit
    monkeypatch.setattr(SASession, "commit", original_commit)

    # Old files must exist — either from restored backup or never touched
    for p in old_paths:
        assert (tmp_path / p).is_file(), f"Old asset file {p} must be restored"


def test_rebuild_is_idempotent(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    r1 = rebuild_page_assets(db_session, material)
    assert r1["status"] == "ready"
    count1 = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == v.id
    ).count()

    r2 = rebuild_page_assets(db_session, material)
    assert r2["status"] == "ready"
    count2 = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == v.id
    ).count()

    assert count1 == count2 == 3


def test_rebuild_no_stale_staging_or_backup(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    rebuild_page_assets(db_session, material)

    # _lock_path computes page_root as (UPLOAD_DIR / file_path).parent / "pages"
    page_root = tmp_path / "pages"
    if page_root.exists():
        for child in page_root.iterdir():
            assert not child.name.startswith(".v7-staging"), f"Staging dir left: {child}"
            assert not child.name.startswith(".v7-backup"), f"Backup dir left: {child}"
            assert not child.name.startswith(".v7-journal"), f"Journal left: {child}"
            assert not child.name.startswith(".v7-lock"), f"Lock left: {child}"


def test_concurrent_rebuild_returns_busy(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, v = _setup_material(
        db_session, tmp_path, user_id=sample_user.id, course_id=sample_course.id,
    )

    # Simulate a lock already held
    # _lock_path computes: (UPLOAD_DIR / file_path).parent / "pages" / .v7-lock-{id}-{version_id}
    # For file_path="test.pdf", that's tmp_path / "pages" / .v7-lock-{id}-{version_id}
    lock_parent = tmp_path / "pages"
    lock_parent.mkdir(parents=True, exist_ok=True)
    lock_dir = lock_parent / f".v7-lock-{material.id}-{v.id}"
    lock_dir.mkdir(parents=True, exist_ok=True)

    result = rebuild_page_assets(db_session, material)
    assert result["status"] == "busy"
