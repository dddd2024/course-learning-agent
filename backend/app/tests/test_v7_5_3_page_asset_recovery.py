from __future__ import annotations

import hashlib
import json
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

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, format="PNG")
    return buf.getvalue()


def _pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "page one")
    doc.save(path)
    doc.close()


def _material(db, tmp_path, user_id: int, course_id: int):
    _pdf(tmp_path / "source.pdf")
    material = Material(
        user_id=user_id,
        course_id=course_id,
        filename="source.pdf",
        file_type="pdf",
        file_path="source.pdf",
        status="ready",
        version=1,
    )
    db.add(material)
    db.flush()
    version = MaterialVersion(material_id=material.id, version=1, status="ready")
    db.add(version)
    db.flush()
    material.active_version_id = version.id
    db.add(
        MaterialPage(
            material_id=material.id,
            material_version_id=version.id,
            page_no=1,
            page_type="text",
            raw_text="page one",
        )
    )
    version_dir = tmp_path / "pages" / "v1"
    version_dir.mkdir(parents=True)
    old = _png((255, 0, 0))
    old_file = version_dir / "page-0001.png"
    old_file.write_bytes(old)
    db.add(
        MaterialPageAsset(
            material_id=material.id,
            material_version_id=version.id,
            page_no=1,
            asset_path="pages/v1/page-0001.png",
            sha256=hashlib.sha256(old).hexdigest(),
            render_status="ready",
        )
    )
    db.commit()
    return material, version, version_dir, old


def _journal(
    path: Path,
    *,
    material: Material,
    version: MaterialVersion,
    version_dir: Path,
    backup_dir: Path,
    old_manifest: list[dict],
    new_manifest: list[dict],
    stage: str = "db_replacing",
):
    service._write_journal(
        path,
        material_id=material.id,
        version_id=version.id,
        stage=stage,
        staging_dir=str(version_dir.parent / ".staging"),
        version_dir=str(version_dir),
        backup_dir=str(backup_dir),
        old_manifest=old_manifest,
        new_manifest=new_manifest,
    )


def test_recovery_runs_only_after_owned_lock(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version, _, _ = _material(
        db_session, tmp_path, sample_user.id, sample_course.id
    )
    observed = {"called": False}

    def fake_recover(db, current, page_root, version_id):
        observed["called"] = True
        assert service._lock_path(current, version_id).is_dir()
        return service.evaluate_page_asset_coverage(db, current)

    monkeypatch.setattr(service, "_recover_incomplete_rebuild", fake_recover)
    result = service.rebuild_page_assets(db_session, material)
    assert observed["called"] is True
    assert result["status"] == "ready"


def test_release_cannot_delete_another_owners_lock(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version, _, _ = _material(
        db_session, tmp_path, sample_user.id, sample_course.id
    )
    lock = service._acquire_lock(material, version.id)
    assert lock is not None
    owner_path = lock.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["owner_token"] = "replacement-owner"
    service._atomic_write_json(owner_path, owner)

    service._release_lock(lock)
    assert lock.path.is_dir()
    assert json.loads(owner_path.read_text(encoding="utf-8"))["owner_token"] == "replacement-owner"


def test_active_heartbeat_lock_is_not_stolen(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version, _, _ = _material(
        db_session, tmp_path, sample_user.id, sample_course.id
    )
    first = service._acquire_lock(material, version.id)
    assert first is not None
    try:
        assert service._acquire_lock(material, version.id) is None
    finally:
        service._release_lock(first)


def test_precommit_crash_restores_old_directory_from_manifest(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version, version_dir, old_bytes = _material(
        db_session, tmp_path, sample_user.id, sample_course.id
    )
    old_manifest = service._db_manifest(db_session, version.id)
    backup_dir = version_dir.parent / ".backup"
    version_dir.replace(backup_dir)
    version_dir.mkdir()
    new_bytes = _png((0, 255, 0))
    (version_dir / "page-0001.png").write_bytes(new_bytes)
    new_manifest = [
        {
            "page_no": 1,
            "filename": "page-0001.png",
            "sha256": hashlib.sha256(new_bytes).hexdigest(),
        }
    ]
    journal = version_dir.parent / f".v7-journal-{material.id}-{version.id}-case.json"
    _journal(
        journal,
        material=material,
        version=version,
        version_dir=version_dir,
        backup_dir=backup_dir,
        old_manifest=old_manifest,
        new_manifest=new_manifest,
    )

    lock = service._acquire_lock(material, version.id)
    assert lock is not None
    try:
        result = service._recover_incomplete_rebuild(
            db_session, material, version_dir.parent, version.id
        )
    finally:
        service._release_lock(lock)

    assert result is None
    assert (version_dir / "page-0001.png").read_bytes() == old_bytes
    assert not backup_dir.exists()
    assert not journal.exists()


def test_postcommit_crash_keeps_new_directory_and_removes_backup(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version, version_dir, _ = _material(
        db_session, tmp_path, sample_user.id, sample_course.id
    )
    old_manifest = service._db_manifest(db_session, version.id)
    backup_dir = version_dir.parent / ".backup"
    version_dir.replace(backup_dir)
    version_dir.mkdir()
    new_bytes = _png((0, 255, 0))
    (version_dir / "page-0001.png").write_bytes(new_bytes)
    new_hash = hashlib.sha256(new_bytes).hexdigest()
    asset = db_session.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_version_id == version.id
    ).one()
    asset.sha256 = new_hash
    db_session.commit()
    new_manifest = [{"page_no": 1, "filename": "page-0001.png", "sha256": new_hash}]
    journal = version_dir.parent / f".v7-journal-{material.id}-{version.id}-case.json"
    _journal(
        journal,
        material=material,
        version=version,
        version_dir=version_dir,
        backup_dir=backup_dir,
        old_manifest=old_manifest,
        new_manifest=new_manifest,
    )

    lock = service._acquire_lock(material, version.id)
    assert lock is not None
    try:
        result = service._recover_incomplete_rebuild(
            db_session, material, version_dir.parent, version.id
        )
    finally:
        service._release_lock(lock)

    assert result is None
    assert (version_dir / "page-0001.png").read_bytes() == new_bytes
    assert not backup_dir.exists()
    assert not journal.exists()


def test_ambiguous_manifest_preserves_all_evidence(
    db_session, sample_user, sample_course, tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    material, version, version_dir, _ = _material(
        db_session, tmp_path, sample_user.id, sample_course.id
    )
    backup_dir = version_dir.parent / ".backup"
    version_dir.replace(backup_dir)
    version_dir.mkdir()
    new_bytes = _png((0, 255, 0))
    (version_dir / "page-0001.png").write_bytes(new_bytes)
    journal = version_dir.parent / f".v7-journal-{material.id}-{version.id}-case.json"
    _journal(
        journal,
        material=material,
        version=version,
        version_dir=version_dir,
        backup_dir=backup_dir,
        old_manifest=[{"page_no": 1, "filename": "page-0001.png", "sha256": "old"}],
        new_manifest=[{"page_no": 1, "filename": "page-0001.png", "sha256": "new"}],
    )

    lock = service._acquire_lock(material, version.id)
    assert lock is not None
    try:
        result = service._recover_incomplete_rebuild(
            db_session, material, version_dir.parent, version.id
        )
    finally:
        service._release_lock(lock)

    assert result["status"] == "recovery_required"
    assert result["code"] == "DB_MANIFEST_AMBIGUOUS"
    assert journal.exists()
    assert backup_dir.exists()
    assert version_dir.exists()
