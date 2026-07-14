"""Page-asset coverage, repair, and crash-safe rebuild services.

V7.5.3 combines actual page-number coverage, an owner-token lock with
heartbeat, journaled old/new manifests, and DB/filesystem compensation.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import fitz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.material import Material
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.retrieval.page_renderer import render_pdf_pages

logger = logging.getLogger(__name__)

LOCK_HEARTBEAT_SECONDS = 15
LOCK_STALE_SECONDS = 120


def _decode_and_verify(path: Path, expected_sha256: str | None) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        from PIL import Image

        payload = path.read_bytes()
        with Image.open(io.BytesIO(payload)) as decoded:
            decoded.verify()
        return not expected_sha256 or hashlib.sha256(payload).hexdigest() == expected_sha256
    except Exception:
        return False


def _expected_page_numbers(db: Session, material: Material) -> list[int]:
    if not material.active_version_id:
        return []
    rows = (
        db.query(MaterialPage.page_no)
        .filter(MaterialPage.material_version_id == material.active_version_id)
        .all()
    )
    expected = sorted({row[0] for row in rows if row[0] and row[0] > 0})
    if expected:
        return expected

    source = Path(settings.UPLOAD_DIR) / material.file_path
    if source.is_file():
        try:
            with fitz.open(str(source)) as pdf:
                return list(range(1, len(pdf) + 1))
        except Exception:
            logger.warning("Unable to read PDF page count for material %s", material.id)
    return []


def evaluate_page_asset_coverage(db: Session, material: Material) -> dict:
    empty = {
        "expected_pages": 0,
        "ready_pages": 0,
        "missing_pages": 0,
        "missing_page_numbers": [],
        "invalid_page_numbers": [],
        "duplicate_page_numbers": [],
        "extra_page_numbers": [],
    }
    if material.file_type.lower() != "pdf":
        return {**empty, "status": "not_applicable"}
    if not material.active_version_id:
        return {**empty, "status": "missing"}

    version_id = material.active_version_id
    assets = (
        db.query(MaterialPageAsset)
        .filter(MaterialPageAsset.material_version_id == version_id)
        .all()
    )
    expected_numbers = _expected_page_numbers(db, material)
    if not expected_numbers:
        max_page = max((row.page_no for row in assets if row.page_no and row.page_no > 0), default=0)
        if max_page:
            expected_numbers = list(range(1, max_page + 1))
    if not expected_numbers:
        return {**empty, "status": "missing"}

    expected_set = set(expected_numbers)
    counts = Counter(row.page_no for row in assets if row.page_no is not None)
    duplicates = sorted(page_no for page_no, count in counts.items() if count > 1)
    ready_numbers: set[int] = set()
    invalid_numbers: set[int] = set()
    upload_root = Path(settings.UPLOAD_DIR)

    for asset in assets:
        if not asset.page_no or asset.page_no not in expected_set:
            continue
        if asset.render_status != "ready" or not asset.asset_path:
            invalid_numbers.add(asset.page_no)
            continue
        if _decode_and_verify(upload_root / asset.asset_path, asset.sha256):
            ready_numbers.add(asset.page_no)
        else:
            invalid_numbers.add(asset.page_no)

    missing_numbers = sorted(expected_set - ready_numbers)
    extras = sorted({row.page_no for row in assets if row.page_no and row.page_no not in expected_set})
    ready_pages = len(ready_numbers)
    expected_pages = len(expected_numbers)
    missing_pages = expected_pages - ready_pages
    has_issues = bool(duplicates or invalid_numbers or extras)
    if missing_pages == 0 and not has_issues:
        status = "ready"
    elif ready_pages:
        status = "partial"
    else:
        status = "missing"

    return {
        "expected_pages": expected_pages,
        "ready_pages": ready_pages,
        "missing_pages": missing_pages,
        "missing_page_numbers": missing_numbers,
        "invalid_page_numbers": sorted(invalid_numbers),
        "duplicate_page_numbers": duplicates,
        "extra_page_numbers": extras,
        "status": status,
    }


def _page_root(material: Material) -> Path:
    return (Path(settings.UPLOAD_DIR) / material.file_path).parent / "pages"


def _lock_path(material: Material, version_id: int) -> Path:
    return _page_root(material) / f".v7-lock-{material.id}-{version_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp() if value else None
    except Exception:
        return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{uuid4().hex}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


@dataclass
class _OwnedLock:
    path: Path
    owner_token: str
    stop_event: threading.Event
    heartbeat_thread: threading.Thread


def _owner_file(lock_dir: Path) -> Path:
    return lock_dir / "owner.json"


def _read_owner(lock_dir: Path) -> dict | None:
    try:
        return json.loads(_owner_file(lock_dir).read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_owner(lock_dir: Path, owner: dict) -> None:
    _atomic_write_json(_owner_file(lock_dir), owner)


def _lock_is_stale(lock_dir: Path) -> bool:
    owner = _read_owner(lock_dir)
    heartbeat = _parse_time((owner or {}).get("heartbeat_at"))
    if heartbeat is not None:
        return time.time() - heartbeat > LOCK_STALE_SECONDS
    try:
        return time.time() - lock_dir.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


def _acquire_lock(material: Material, version_id: int) -> _OwnedLock | None:
    lock_dir = _lock_path(material, version_id)
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    owner_token = uuid4().hex
    try:
        lock_dir.mkdir(exist_ok=False)
    except FileExistsError:
        if not _lock_is_stale(lock_dir):
            return None
        stale_dir = lock_dir.with_name(f"{lock_dir.name}.stale-{uuid4().hex}")
        try:
            lock_dir.replace(stale_dir)
            lock_dir.mkdir(exist_ok=False)
        except (FileExistsError, FileNotFoundError, PermissionError, OSError):
            return None
        finally:
            shutil.rmtree(stale_dir, ignore_errors=True)

    owner = {
        "owner_token": owner_token,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started_at": _utc_now(),
        "heartbeat_at": _utc_now(),
        "material_id": material.id,
        "version_id": version_id,
    }
    _write_owner(lock_dir, owner)
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(LOCK_HEARTBEAT_SECONDS):
            current = _read_owner(lock_dir)
            if not current or current.get("owner_token") != owner_token:
                return
            current["heartbeat_at"] = _utc_now()
            try:
                _write_owner(lock_dir, current)
            except Exception:
                logger.warning("Failed to heartbeat page-asset lock %s", lock_dir)

    thread = threading.Thread(
        target=heartbeat,
        name=f"page-asset-lock-{material.id}-{version_id}",
        daemon=True,
    )
    thread.start()
    return _OwnedLock(lock_dir, owner_token, stop_event, thread)


def _release_lock(lock: _OwnedLock) -> None:
    lock.stop_event.set()
    lock.heartbeat_thread.join(timeout=2)
    current = _read_owner(lock.path)
    if current and current.get("owner_token") == lock.owner_token:
        shutil.rmtree(lock.path, ignore_errors=True)


def _manifest_record(page_no: int, filename: str, sha256: str | None) -> dict:
    return {"page_no": int(page_no), "filename": Path(filename).name, "sha256": sha256 or ""}


def _normalise_manifest(records: list[dict]) -> list[dict]:
    return sorted(
        [
            _manifest_record(record["page_no"], record["filename"], record.get("sha256"))
            for record in records
        ],
        key=lambda item: (item["page_no"], item["filename"], item["sha256"]),
    )


def _db_manifest(db: Session, version_id: int) -> list[dict]:
    rows = (
        db.query(MaterialPageAsset)
        .filter(MaterialPageAsset.material_version_id == version_id)
        .all()
    )
    return _normalise_manifest(
        [
            {"page_no": row.page_no, "filename": row.asset_path, "sha256": row.sha256}
            for row in rows
            if row.page_no and row.asset_path
        ]
    )


def _render_manifest(rendered) -> list[dict]:
    return _normalise_manifest(
        [
            {"page_no": item.page_no, "filename": item.filename, "sha256": item.sha256}
            for item in rendered
        ]
    )


def _directory_matches_manifest(directory: Path, manifest: list[dict]) -> bool:
    """Compare the exact direct-file set and SHA-256 values to a manifest."""
    manifest = _normalise_manifest(manifest)
    if not directory.exists():
        return not manifest
    if not directory.is_dir():
        return False
    actual_files = sorted(path for path in directory.iterdir() if path.is_file())
    expected_names = sorted(record["filename"] for record in manifest)
    if [path.name for path in actual_files] != expected_names:
        return False
    expected_hashes = {record["filename"]: record["sha256"] for record in manifest}
    for path in actual_files:
        expected_hash = expected_hashes[path.name]
        if expected_hash and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            return False
    return True


def _write_journal(path: Path, **payload) -> None:
    _atomic_write_json(path, {**payload, "updated_at": _utc_now()})


def _read_journal(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def _restore_backup(version_dir: Path, backup_dir: Path, old_manifest: list[dict], new_manifest: list[dict]) -> bool:
    """Restore a verified old backup without deleting ambiguous evidence."""
    if not backup_dir.exists() or not _directory_matches_manifest(backup_dir, old_manifest):
        return False
    if version_dir.exists() and not _directory_matches_manifest(version_dir, new_manifest):
        return False
    trash: Path | None = None
    try:
        if version_dir.exists():
            trash = version_dir.with_name(f"{version_dir.name}.trash-{uuid4().hex}")
            version_dir.replace(trash)
        backup_dir.replace(version_dir)
        if trash is not None:
            _remove_path(trash)
        return _directory_matches_manifest(version_dir, old_manifest)
    except Exception:
        logger.exception("Failed to restore page-asset backup %s", backup_dir)
        return False


def _recovery_required(db: Session, material: Material, code: str, journal_path: Path, **details) -> dict:
    return {
        **evaluate_page_asset_coverage(db, material),
        "status": "recovery_required",
        "code": code,
        "journal": str(journal_path),
        **details,
    }


def _recover_incomplete_rebuild(
    db: Session,
    material: Material,
    page_root: Path,
    version_id: int,
) -> dict | None:
    """Recover journals while the caller owns the material/version lock."""
    prefix = f".v7-journal-{material.id}-{version_id}-"
    for journal_path in sorted(page_root.glob(f"{prefix}*")):
        journal = _read_journal(journal_path)
        if not journal:
            return _recovery_required(db, material, "JOURNAL_UNREADABLE", journal_path)

        stage = journal.get("stage")
        staging_dir = Path(journal.get("staging_dir", ""))
        version_dir = Path(journal.get("version_dir", ""))
        backup_dir = Path(journal.get("backup_dir", ""))
        old_manifest = _normalise_manifest(journal.get("old_manifest", []))
        new_manifest = _normalise_manifest(journal.get("new_manifest", []))

        if stage == "rendering":
            _remove_path(staging_dir)
            journal_path.unlink(missing_ok=True)
            continue
        if stage == "recovery_required":
            return _recovery_required(db, material, "PREVIOUS_RECOVERY_REQUIRED", journal_path)

        db_manifest = _db_manifest(db, version_id)
        if stage in {"promoting", "db_replacing"}:
            if db_manifest == new_manifest and new_manifest:
                if not _directory_matches_manifest(version_dir, new_manifest):
                    return _recovery_required(
                        db,
                        material,
                        "NEW_DB_DIRECTORY_MISMATCH",
                        journal_path,
                        db_manifest=db_manifest,
                        new_manifest=new_manifest,
                    )
                _remove_path(backup_dir)
                _remove_path(staging_dir)
                journal_path.unlink(missing_ok=True)
                continue

            if db_manifest == old_manifest:
                # Crash before the old directory was moved: it is already the
                # correct readable version. Never rename/delete it just because
                # a promoting journal exists.
                if not backup_dir.exists() and _directory_matches_manifest(version_dir, old_manifest):
                    _remove_path(staging_dir)
                    journal_path.unlink(missing_ok=True)
                    continue

                # Crash after backup and possibly after promotion: restore only
                # when both old and new directories match their journal manifests.
                if backup_dir.exists() and _restore_backup(
                    version_dir, backup_dir, old_manifest, new_manifest
                ):
                    _remove_path(staging_dir)
                    journal_path.unlink(missing_ok=True)
                    continue

                # First-ever build: the old manifest is empty and DB still has
                # no rows. A promoted directory matching the new manifest is
                # uncommitted and can be discarded safely.
                if (
                    not old_manifest
                    and not backup_dir.exists()
                    and _directory_matches_manifest(version_dir, new_manifest)
                ):
                    _remove_path(version_dir)
                    _remove_path(staging_dir)
                    journal_path.unlink(missing_ok=True)
                    continue
                if not old_manifest and not version_dir.exists() and not backup_dir.exists():
                    _remove_path(staging_dir)
                    journal_path.unlink(missing_ok=True)
                    continue

                return _recovery_required(
                    db,
                    material,
                    "OLD_DB_DIRECTORY_AMBIGUOUS",
                    journal_path,
                    db_manifest=db_manifest,
                    old_manifest=old_manifest,
                    new_manifest=new_manifest,
                )

            return _recovery_required(
                db,
                material,
                "DB_MANIFEST_AMBIGUOUS",
                journal_path,
                db_manifest=db_manifest,
                old_manifest=old_manifest,
                new_manifest=new_manifest,
            )

        if stage == "committed":
            if db_manifest != new_manifest or not _directory_matches_manifest(version_dir, new_manifest):
                return _recovery_required(
                    db,
                    material,
                    "COMMITTED_MANIFEST_MISMATCH",
                    journal_path,
                    db_manifest=db_manifest,
                    new_manifest=new_manifest,
                )
            _remove_path(backup_dir)
            _remove_path(staging_dir)
            journal_path.unlink(missing_ok=True)
            continue

        return _recovery_required(db, material, "UNKNOWN_JOURNAL_STAGE", journal_path)
    return None


def ensure_active_page_assets(db: Session, material: Material) -> dict:
    current = evaluate_page_asset_coverage(db, material)
    if current["status"] in {"ready", "not_applicable"}:
        return current
    return rebuild_page_assets(db, material)


def rebuild_page_assets(db: Session, material: Material) -> dict:
    if material.file_type.lower() != "pdf":
        return {**evaluate_page_asset_coverage(db, material), "status": "not_applicable"}
    if not material.active_version_id:
        return evaluate_page_asset_coverage(db, material)
    source = Path(settings.UPLOAD_DIR) / material.file_path
    if not source.is_file():
        return evaluate_page_asset_coverage(db, material)

    version_id = material.active_version_id
    page_root = _page_root(material)
    page_root.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(material, version_id)
    if lock is None:
        return {
            **evaluate_page_asset_coverage(db, material),
            "status": "busy",
            "code": "REBUILD_BUSY",
        }
    try:
        recovery = _recover_incomplete_rebuild(db, material, page_root, version_id)
        if recovery is not None:
            return recovery
        return _do_rebuild(db, material, source, page_root, version_id)
    finally:
        _release_lock(lock)


def _do_rebuild(
    db: Session,
    material: Material,
    source: Path,
    page_root: Path,
    version_id: int,
) -> dict:
    expected_numbers = _expected_page_numbers(db, material)
    if not expected_numbers:
        return evaluate_page_asset_coverage(db, material)

    token = uuid4().hex
    staging_dir = page_root / f".v7-staging-rebuild-{material.id}-{version_id}-{token}"
    version_dir = page_root / f"v{material.version}"
    backup_dir = page_root / f".v7-backup-{material.id}-{version_id}-{token}"
    journal_path = page_root / f".v7-journal-{material.id}-{version_id}-{token}.json"
    old_manifest = _db_manifest(db, version_id)

    _write_journal(
        journal_path,
        material_id=material.id,
        version_id=version_id,
        stage="rendering",
        staging_dir=str(staging_dir),
        version_dir=str(version_dir),
        backup_dir=str(backup_dir),
        old_manifest=old_manifest,
        new_manifest=[],
    )
    try:
        rendered = list(render_pdf_pages(source, staging_dir))
    except Exception:
        logger.exception("Page-asset render failed for material %s", material.id)
        _remove_path(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    rendered_numbers = sorted(item.page_no for item in rendered)
    if rendered_numbers != expected_numbers or any(
        not _decode_and_verify(staging_dir / item.filename, item.sha256)
        for item in rendered
    ):
        logger.warning(
            "Page-asset staging validation failed for material %s: expected=%s rendered=%s",
            material.id,
            expected_numbers,
            rendered_numbers,
        )
        _remove_path(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    new_manifest = _render_manifest(rendered)
    _write_journal(
        journal_path,
        material_id=material.id,
        version_id=version_id,
        stage="promoting",
        staging_dir=str(staging_dir),
        version_dir=str(version_dir),
        backup_dir=str(backup_dir),
        old_manifest=old_manifest,
        new_manifest=new_manifest,
    )

    had_existing = version_dir.exists()
    try:
        if had_existing:
            version_dir.replace(backup_dir)
        staging_dir.replace(version_dir)
    except Exception:
        logger.exception("Page-asset directory promotion failed for material %s", material.id)
        if had_existing and backup_dir.exists() and not version_dir.exists():
            backup_dir.replace(version_dir)
        _remove_path(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    _write_journal(
        journal_path,
        material_id=material.id,
        version_id=version_id,
        stage="db_replacing",
        staging_dir=str(staging_dir),
        version_dir=str(version_dir),
        backup_dir=str(backup_dir),
        old_manifest=old_manifest,
        new_manifest=new_manifest,
    )

    upload_root = Path(settings.UPLOAD_DIR)
    try:
        (
            db.query(MaterialPageAsset)
            .filter(MaterialPageAsset.material_version_id == version_id)
            .delete(synchronize_session=False)
        )
        for item in rendered:
            db.add(
                MaterialPageAsset(
                    material_id=material.id,
                    material_version_id=version_id,
                    page_no=item.page_no,
                    asset_path=str((version_dir / item.filename).relative_to(upload_root)).replace("\\", "/"),
                    width=item.width,
                    height=item.height,
                    dpi=item.dpi,
                    sha256=item.sha256,
                    render_status="ready",
                )
            )
        db.flush()
        db.commit()
    except Exception:
        logger.exception("Page-asset DB replacement failed for material %s", material.id)
        db.rollback()
        if backup_dir.exists() and _restore_backup(
            version_dir, backup_dir, old_manifest, new_manifest
        ):
            journal_path.unlink(missing_ok=True)
            return evaluate_page_asset_coverage(db, material)
        if not old_manifest and _directory_matches_manifest(version_dir, new_manifest):
            _remove_path(version_dir)
            journal_path.unlink(missing_ok=True)
            return evaluate_page_asset_coverage(db, material)
        _write_journal(
            journal_path,
            material_id=material.id,
            version_id=version_id,
            stage="recovery_required",
            staging_dir=str(staging_dir),
            version_dir=str(version_dir),
            backup_dir=str(backup_dir),
            old_manifest=old_manifest,
            new_manifest=new_manifest,
        )
        return _recovery_required(
            db,
            material,
            "DB_FAILURE_RESTORE_FAILED",
            journal_path,
            old_manifest=old_manifest,
            new_manifest=new_manifest,
        )

    _write_journal(
        journal_path,
        material_id=material.id,
        version_id=version_id,
        stage="committed",
        staging_dir=str(staging_dir),
        version_dir=str(version_dir),
        backup_dir=str(backup_dir),
        old_manifest=old_manifest,
        new_manifest=new_manifest,
    )
    _remove_path(backup_dir)
    _remove_path(staging_dir)
    journal_path.unlink(missing_ok=True)
    return evaluate_page_asset_coverage(db, material)
