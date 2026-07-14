"""Page-asset coverage, repair, and crash-safe rebuild services.

V7.5.3 keeps page rendering recoverable across process crashes by combining:
- actual page-number coverage validation;
- an owner-token lock with heartbeat;
- a journal containing old/new asset manifests; and
- database/file-system compensation based on manifest equality.
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
    """Return True when a page image exists, decodes, and matches its hash."""
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
    """Compute active-version page coverage from actual expected page numbers."""
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

    expected_numbers = _expected_page_numbers(db, material)
    version_id = material.active_version_id
    assets = (
        db.query(MaterialPageAsset)
        .filter(MaterialPageAsset.material_version_id == version_id)
        .all()
    )

    # Very old records can lack MaterialPage rows and the source PDF may be
    # temporarily unavailable.  Existing asset page numbers are only a last
    # resort; they are never preferred over the real PDF/page IR.
    if not expected_numbers:
        max_page = max((a.page_no for a in assets if a.page_no and a.page_no > 0), default=0)
        if max_page:
            expected_numbers = list(range(1, max_page + 1))
    if not expected_numbers:
        return {**empty, "status": "missing"}

    expected_set = set(expected_numbers)
    counts = Counter(a.page_no for a in assets if a.page_no is not None)
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
    extras = sorted({a.page_no for a in assets if a.page_no and a.page_no not in expected_set})
    ready_pages = len(ready_numbers)
    expected_pages = len(expected_numbers)
    missing_pages = expected_pages - ready_pages
    has_issues = bool(duplicates or invalid_numbers or extras)

    if missing_pages == 0 and not has_issues:
        status = "ready"
    elif ready_pages > 0:
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
    source = Path(settings.UPLOAD_DIR) / material.file_path
    return source.parent / "pages"


def _lock_path(material: Material, version_id: int) -> Path:
    return _page_root(material) / f".v7-lock-{material.id}-{version_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
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
    token = uuid4().hex

    while True:
        try:
            lock_dir.mkdir(exist_ok=False)
            break
        except FileExistsError:
            if not _lock_is_stale(lock_dir):
                return None
            stale_dir = lock_dir.with_name(f"{lock_dir.name}.stale-{uuid4().hex}")
            try:
                lock_dir.replace(stale_dir)
            except (FileExistsError, FileNotFoundError, PermissionError, OSError):
                return None
            shutil.rmtree(stale_dir, ignore_errors=True)

    owner = {
        "owner_token": token,
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
            if not current or current.get("owner_token") != token:
                return
            current["heartbeat_at"] = _utc_now()
            try:
                _write_owner(lock_dir, current)
            except Exception:
                logger.warning("Failed to heartbeat page-asset lock %s", lock_dir)

    thread = threading.Thread(target=heartbeat, name=f"page-asset-lock-{material.id}", daemon=True)
    thread.start()
    return _OwnedLock(lock_dir, token, stop_event, thread)


def _release_lock(lock: _OwnedLock) -> None:
    lock.stop_event.set()
    lock.heartbeat_thread.join(timeout=2)
    current = _read_owner(lock.path)
    if current and current.get("owner_token") == lock.owner_token:
        shutil.rmtree(lock.path, ignore_errors=True)


def _manifest_record(page_no: int, filename: str, sha256: str | None) -> dict:
    return {"page_no": int(page_no), "filename": filename, "sha256": sha256 or ""}


def _normalise_manifest(records: list[dict]) -> list[dict]:
    return sorted(
        [
            _manifest_record(record["page_no"], Path(record["filename"]).name, record.get("sha256"))
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
            {
                "page_no": row.page_no,
                "filename": Path(row.asset_path or "").name,
                "sha256": row.sha256,
            }
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


def _restore_old_directory(version_dir: Path, backup_dir: Path) -> bool:
    trash: Path | None = None
    try:
        if version_dir.exists():
            trash = version_dir.with_name(f"{version_dir.name}.trash-{uuid4().hex}")
            version_dir.replace(trash)
        if backup_dir.exists():
            backup_dir.replace(version_dir)
        elif trash is not None:
            # No historical directory existed; remove the promoted new one.
            _remove_path(trash)
            return True
        if trash is not None:
            _remove_path(trash)
        return version_dir.exists()
    except Exception:
        logger.exception("Failed to restore page-asset backup %s", backup_dir)
        return False


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
            return {
                **evaluate_page_asset_coverage(db, material),
                "status": "recovery_required",
                "code": "JOURNAL_UNREADABLE",
                "journal": str(journal_path),
            }

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

        db_manifest = _db_manifest(db, version_id)
        if stage in {"promoting", "db_replacing"}:
            if db_manifest == new_manifest and new_manifest:
                if not version_dir.exists():
                    return {
                        **evaluate_page_asset_coverage(db, material),
                        "status": "recovery_required",
                        "code": "NEW_DB_WITHOUT_NEW_DIRECTORY",
                        "journal": str(journal_path),
                    }
                _remove_path(backup_dir)
                _remove_path(staging_dir)
                journal_path.unlink(missing_ok=True)
                continue
            if db_manifest == old_manifest:
                if not _restore_old_directory(version_dir, backup_dir):
                    return {
                        **evaluate_page_asset_coverage(db, material),
                        "status": "recovery_required",
                        "code": "OLD_DIRECTORY_RESTORE_FAILED",
                        "journal": str(journal_path),
                    }
                _remove_path(staging_dir)
                journal_path.unlink(missing_ok=True)
                continue
            return {
                **evaluate_page_asset_coverage(db, material),
                "status": "recovery_required",
                "code": "DB_MANIFEST_AMBIGUOUS",
                "journal": str(journal_path),
                "db_manifest": db_manifest,
                "old_manifest": old_manifest,
                "new_manifest": new_manifest,
            }

        if stage == "committed":
            if db_manifest != new_manifest:
                return {
                    **evaluate_page_asset_coverage(db, material),
                    "status": "recovery_required",
                    "code": "COMMITTED_MANIFEST_MISMATCH",
                    "journal": str(journal_path),
                }
            _remove_path(backup_dir)
            _remove_path(staging_dir)
            journal_path.unlink(missing_ok=True)
            continue

        return {
            **evaluate_page_asset_coverage(db, material),
            "status": "recovery_required",
            "code": "UNKNOWN_JOURNAL_STAGE",
            "journal": str(journal_path),
        }
    return None


def ensure_active_page_assets(db: Session, material: Material) -> dict:
    """Return current coverage or rebuild incomplete active PDF assets."""
    current = evaluate_page_asset_coverage(db, material)
    if current["status"] in {"ready", "not_applicable"}:
        return current
    return rebuild_page_assets(db, material)


def rebuild_page_assets(db: Session, material: Material) -> dict:
    """Render and replace active page assets with lock-owned compensation."""
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
        return {**evaluate_page_asset_coverage(db, material), "status": "busy", "code": "REBUILD_BUSY"}

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
    if rendered_numbers != expected_numbers:
        logger.warning(
            "Page-asset rebuild page set mismatch for material %s: expected=%s rendered=%s",
            material.id,
            expected_numbers,
            rendered_numbers,
        )
        _remove_path(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    for item in rendered:
        if not _decode_and_verify(staging_dir / item.filename, item.sha256):
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
        restored = _restore_old_directory(version_dir, backup_dir)
        if restored:
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
        return {
            **evaluate_page_asset_coverage(db, material),
            "status": "recovery_required",
            "code": "DB_FAILURE_RESTORE_FAILED",
            "journal": str(journal_path),
        }

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
