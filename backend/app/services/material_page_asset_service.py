"""Page-asset integrity checking and backfill for existing PDF materials.

V7.5.2-02: evaluate_page_asset_coverage() is the single source of truth
for page-asset completeness, using actual page-number sets instead of
record counts.

V7.5.2-03: rebuild_page_assets() uses a lock, journal, and compensation
transaction to guarantee the old readable version survives any failure.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
from collections import Counter
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


# ── V7.5.2-02: Unified page-asset coverage ──────────────────────────

def _decode_and_verify(path: Path, expected_sha256: str | None) -> bool:
    """Return True if the file exists, is non-empty, decodable, and hash matches."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        from PIL import Image
        payload = path.read_bytes()
        with Image.open(io.BytesIO(payload)) as decoded:
            decoded.verify()
        if expected_sha256:
            return hashlib.sha256(payload).hexdigest() == expected_sha256
        return True
    except Exception:
        return False


def evaluate_page_asset_coverage(db: Session, material: Material) -> dict:
    """Compute page-asset coverage for the active version.

    Returns a dict with:
    - expected_pages: number of pages expected (from MaterialPage or PDF)
    - ready_pages: number of pages with valid, decodable assets
    - missing_pages: expected - ready
    - missing_page_numbers: list of page numbers without valid assets
    - invalid_page_numbers: list of page numbers with corrupt/hash-mismatch assets
    - duplicate_page_numbers: list of page numbers with multiple assets
    - extra_page_numbers: list of asset page numbers outside expected set
    - status: 'ready' | 'partial' | 'missing' | 'not_applicable'
    """
    if material.file_type.lower() != "pdf":
        return {
            "expected_pages": 0, "ready_pages": 0, "missing_pages": 0,
            "missing_page_numbers": [], "invalid_page_numbers": [],
            "duplicate_page_numbers": [], "extra_page_numbers": [],
            "status": "not_applicable",
        }

    if not material.active_version_id:
        return {
            "expected_pages": 0, "ready_pages": 0, "missing_pages": 0,
            "missing_page_numbers": [], "invalid_page_numbers": [],
            "duplicate_page_numbers": [], "extra_page_numbers": [],
            "status": "missing",
        }

    version_id = material.active_version_id
    upload_dir = Path(settings.UPLOAD_DIR)

    # 1. Determine expected page numbers
    page_rows = (
        db.query(MaterialPage.page_no)
        .filter(MaterialPage.material_version_id == version_id)
        .all()
    )
    expected_page_numbers = sorted({row[0] for row in page_rows if row[0]})

    if not expected_page_numbers:
        # Fallback: read PDF page count
        source = upload_dir / material.file_path
        if source.is_file():
            try:
                pdf = fitz.open(str(source))
                expected_page_numbers = list(range(1, len(pdf) + 1))
                pdf.close()
            except Exception:
                pass

    if not expected_page_numbers:
        # Last resort: use max page_no from existing assets
        assets_for_pages = (
            db.query(MaterialPageAsset.page_no)
            .filter(MaterialPageAsset.material_version_id == version_id)
            .all()
        )
        max_page = max((r[0] for r in assets_for_pages if r[0]), default=0)
        if max_page > 0:
            expected_page_numbers = list(range(1, max_page + 1))

    if not expected_page_numbers:
        return {
            "expected_pages": 0, "ready_pages": 0, "missing_pages": 0,
            "missing_page_numbers": [], "invalid_page_numbers": [],
            "duplicate_page_numbers": [], "extra_page_numbers": [],
            "status": "missing",
        }

    expected_set = set(expected_page_numbers)

    # 2. Gather all assets for the active version
    assets = (
        db.query(MaterialPageAsset)
        .filter(MaterialPageAsset.material_version_id == version_id)
        .all()
    )

    # 3. Detect duplicates
    page_no_counts = Counter(a.page_no for a in assets if a.page_no is not None)
    duplicate_page_numbers = sorted(p for p, c in page_no_counts.items() if c > 1)

    # 4. Check each asset for validity
    ready_page_numbers: set[int] = set()
    invalid_page_numbers: list[int] = []

    for a in assets:
        if a.page_no is None:
            continue
        if a.render_status != "ready" or not a.asset_path:
            continue
        path = upload_dir / a.asset_path
        if _decode_and_verify(path, a.sha256):
            ready_page_numbers.add(a.page_no)
        else:
            if a.page_no in expected_set:
                invalid_page_numbers.append(a.page_no)

    # 5. Compute missing and extra
    missing_page_numbers = sorted(expected_set - ready_page_numbers)
    extra_page_numbers = sorted(
        {a.page_no for a in assets if a.page_no and a.page_no not in expected_set}
    )

    # 6. Determine status — duplicates or invalid pages prevent 'ready'
    ready_pages = len(ready_page_numbers & expected_set)
    expected_pages = len(expected_page_numbers)
    missing_pages = expected_pages - ready_pages

    has_issues = bool(duplicate_page_numbers or invalid_page_numbers)
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
        "missing_page_numbers": missing_page_numbers,
        "invalid_page_numbers": sorted(set(invalid_page_numbers)),
        "duplicate_page_numbers": duplicate_page_numbers,
        "extra_page_numbers": extra_page_numbers,
        "status": status,
    }


# ── V7.5.2-03: Rebuild with compensation transaction ────────────────

def _lock_path(material: Material) -> Path:
    source = Path(settings.UPLOAD_DIR) / material.file_path
    page_root = source.parent / "pages"
    return page_root / f".v7-lock-{material.id}-{material.active_version_id}"


def _acquire_lock(material: Material) -> bool:
    """Try to atomically create a lock directory. Returns True on success."""
    lock = _lock_path(material)
    try:
        lock.mkdir(parents=True, exist_ok=False)
        return True
    except FileExistsError:
        # Check if the lock is stale (older than 10 minutes)
        import time
        try:
            age = time.time() - lock.stat().st_mtime
            if age > 600:
                shutil.rmtree(lock, ignore_errors=True)
                try:
                    lock.mkdir(parents=True, exist_ok=False)
                    return True
                except FileExistsError:
                    return False
        except Exception:
            pass
        return False


def _release_lock(material: Material) -> None:
    lock = _lock_path(material)
    if lock.exists():
        shutil.rmtree(lock, ignore_errors=True)


def _write_journal(journal_path: Path, data: dict) -> None:
    journal_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_journal(journal_path: Path) -> dict | None:
    if not journal_path.exists():
        return None
    try:
        return json.loads(journal_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cleanup_staging(staging_dir: Path) -> None:
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)


def _recover_incomplete_rebuild(
    db: Session, material: Material, page_root: Path, version_id: int,
) -> None:
    """Check for and recover from an incomplete rebuild."""
    journal_pattern = f".v7-journal-{material.id}-{version_id}-"
    if not page_root.exists():
        return

    for child in page_root.iterdir():
        if child.name.startswith(journal_pattern):
            journal = _read_journal(child)
            if journal is None:
                child.unlink(missing_ok=True)
                continue

            backup_dir = Path(journal.get("backup_dir", ""))
            version_dir = Path(journal.get("version_dir", ""))
            stage = journal.get("stage", "")

            if stage in ("promoting", "db_replacing"):
                # DB might have old or new records; check which dir exists
                if backup_dir.exists() and not version_dir.exists():
                    # Old dir was moved to backup but new dir wasn't promoted
                    backup_dir.replace(version_dir)
                elif backup_dir.exists() and version_dir.exists():
                    # Promotion happened but DB commit may have failed
                    # Keep version_dir (new data), clean backup
                    shutil.rmtree(backup_dir, ignore_errors=True)
            elif stage == "rendering":
                # Rendering failed, clean staging
                staging_dir = Path(journal.get("staging_dir", ""))
                _cleanup_staging(staging_dir)

            child.unlink(missing_ok=True)


def ensure_active_page_assets(db: Session, material: Material) -> dict:
    """Check if the active version has complete page assets; rebuild if not."""
    if material.file_type.lower() != "pdf":
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "not_applicable"}

    current = evaluate_page_asset_coverage(db, material)
    if current["missing_pages"] == 0 and not current.get("invalid_page_numbers"):
        return current

    return rebuild_page_assets(db, material)


def rebuild_page_assets(db: Session, material: Material) -> dict:
    """Render the full PDF and atomically replace page assets with compensation.

    V7.5.2-03: Uses a lock, journal, and compensation transaction to
    guarantee the old readable version survives any failure point.
    """
    if material.file_type.lower() != "pdf":
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "not_applicable"}

    if not material.active_version_id:
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "missing"}

    version_id = material.active_version_id
    source = Path(settings.UPLOAD_DIR) / material.file_path
    if not source.is_file():
        return evaluate_page_asset_coverage(db, material)

    page_root = source.parent / "pages"
    page_root.mkdir(parents=True, exist_ok=True)

    # Recover from any incomplete prior rebuild
    _recover_incomplete_rebuild(db, material, page_root, version_id)

    # Acquire lock
    if not _acquire_lock(material):
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "busy"}

    journal_path = page_root / f".v7-journal-{material.id}-{version_id}-{uuid4().hex}"
    staging_dir = page_root / f".v7-staging-rebuild-{material.id}-{version_id}-{uuid4().hex}"
    version_dir = page_root / f"v{material.version}"
    backup_dir = page_root / f".v7-backup-{material.id}-{version_id}-{uuid4().hex}"

    try:
        return _do_rebuild(
            db, material, source, page_root, version_id,
            staging_dir, version_dir, backup_dir, journal_path,
        )
    finally:
        _release_lock(material)


def _do_rebuild(
    db: Session, material: Material, source: Path, page_root: Path,
    version_id: int, staging_dir: Path, version_dir: Path,
    backup_dir: Path, journal_path: Path,
) -> dict:
    """Inner rebuild logic with compensation at every failure point."""

    # 1. Determine expected pages
    page_rows = (
        db.query(MaterialPage.page_no)
        .filter(MaterialPage.material_version_id == version_id)
        .all()
    )
    expected_page_numbers = sorted({row[0] for row in page_rows if row[0]})
    if not expected_page_numbers:
        try:
            pdf = fitz.open(str(source))
            expected_page_numbers = list(range(1, len(pdf) + 1))
            pdf.close()
        except Exception:
            return evaluate_page_asset_coverage(db, material)
        if not expected_page_numbers:
            return evaluate_page_asset_coverage(db, material)

    expected_pages = len(expected_page_numbers)

    # 2. Write journal — rendering stage
    _write_journal(journal_path, {
        "material_id": material.id,
        "version_id": version_id,
        "stage": "rendering",
        "staging_dir": str(staging_dir),
        "version_dir": str(version_dir),
        "backup_dir": str(backup_dir),
    })

    # 3. Render all pages to staging
    try:
        rendered = render_pdf_pages(source, staging_dir)
    except Exception as exc:
        logger.warning("Page-asset rebuild render failed for material %s: %s", material.id, exc)
        _cleanup_staging(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    if len(rendered) != expected_pages:
        logger.warning(
            "Page-asset rebuild page count mismatch for material %s: expected %d, got %d",
            material.id, expected_pages, len(rendered),
        )
        _cleanup_staging(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    # 4. Verify each rendered page in staging
    upload_root = Path(settings.UPLOAD_DIR)
    for r in rendered:
        rendered_path = staging_dir / r.filename
        if not _decode_and_verify(rendered_path, r.sha256):
            logger.warning("Staging page %s failed verification for material %s", r.page_no, material.id)
            _cleanup_staging(staging_dir)
            journal_path.unlink(missing_ok=True)
            return evaluate_page_asset_coverage(db, material)

    # 5. Write journal — promoting stage
    _write_journal(journal_path, {
        "material_id": material.id,
        "version_id": version_id,
        "stage": "promoting",
        "staging_dir": str(staging_dir),
        "version_dir": str(version_dir),
        "backup_dir": str(backup_dir),
    })

    # 6. Move old version_dir to backup
    had_existing = version_dir.exists()
    if had_existing:
        try:
            version_dir.replace(backup_dir)
        except Exception as exc:
            logger.warning("Backup move failed for material %s: %s", material.id, exc)
            _cleanup_staging(staging_dir)
            journal_path.unlink(missing_ok=True)
            return evaluate_page_asset_coverage(db, material)

    # 7. Promote staging to version_dir
    try:
        staging_dir.replace(version_dir)
    except Exception as exc:
        logger.warning("Staging promote failed for material %s: %s", material.id, exc)
        # Restore backup
        if had_existing and backup_dir.exists():
            backup_dir.replace(version_dir)
        _cleanup_staging(staging_dir)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    # 8. Write journal — db_replacing stage
    _write_journal(journal_path, {
        "material_id": material.id,
        "version_id": version_id,
        "stage": "db_replacing",
        "staging_dir": str(staging_dir),
        "version_dir": str(version_dir),
        "backup_dir": str(backup_dir),
    })

    # 9. Replace DB records in a transaction
    try:
        db.query(MaterialPageAsset).filter(
            MaterialPageAsset.material_version_id == version_id
        ).delete(synchronize_session=False)

        for r in rendered:
            asset_path = str((version_dir / r.filename).relative_to(upload_root)).replace("\\", "/")
            db.add(MaterialPageAsset(
                material_id=material.id,
                material_version_id=version_id,
                page_no=r.page_no,
                asset_path=asset_path,
                width=r.width,
                height=r.height,
                dpi=r.dpi,
                sha256=r.sha256,
                render_status="ready",
            ))
        db.flush()
        db.commit()
    except Exception as exc:
        logger.warning("DB replace failed for material %s: %s", material.id, exc)
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.warning("Rollback also failed: %s", rb_exc)
        # Restore old directory using rename (atomic on both Windows/Linux)
        trash_dir: Path | None = None
        if version_dir.exists():
            trash_dir = version_dir.parent / f".v7-trash-{uuid4().hex}"
            try:
                version_dir.rename(trash_dir)
                logger.info("Renamed version_dir to trash for material %s", material.id)
            except Exception as rn_exc:
                logger.warning("Rename version_dir to trash failed: %s", rn_exc)
                trash_dir = None
        else:
            logger.info("version_dir does not exist for material %s", material.id)
        if had_existing and backup_dir.exists():
            try:
                backup_dir.rename(version_dir)
                logger.info("Restored backup to version_dir for material %s", material.id)
            except Exception as rn_exc:
                logger.warning("Rename backup to version_dir failed: %s", rn_exc)
        else:
            logger.info("backup_dir does not exist (had_existing=%s, backup_exists=%s) for material %s", had_existing, backup_dir.exists(), material.id)
        if trash_dir is not None and trash_dir.exists():
            shutil.rmtree(trash_dir, ignore_errors=True)
        journal_path.unlink(missing_ok=True)
        return evaluate_page_asset_coverage(db, material)

    # 10. Success — clean up backup and journal
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
    journal_path.unlink(missing_ok=True)

    # Clean up any stale staging from prior failed runs
    if page_root.exists():
        for child in page_root.iterdir():
            if child.name.startswith(".v7-staging-rebuild-"):
                shutil.rmtree(child, ignore_errors=True)

    return evaluate_page_asset_coverage(db, material)
