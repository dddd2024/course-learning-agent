"""Page-asset integrity checking and backfill for existing PDF materials.

V7.5.1-01: Materials parsed before page rendering was introduced may have
MaterialPage rows but no MaterialPageAsset records.  This service checks
completeness and rebuilds missing page assets in-place for the active version
without requiring a full re-parse.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
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


def _is_asset_valid(asset: MaterialPageAsset, upload_dir: Path) -> bool:
    """Return True if the asset file exists on disk and is non-empty."""
    if asset.render_status != "ready" or not asset.asset_path:
        return False
    path = upload_dir / asset.asset_path
    return path.is_file() and path.stat().st_size > 0


def _page_asset_status(db: Session, material: Material) -> dict:
    """Compute the current page-asset coverage for the active version."""
    if not material.active_version_id:
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "missing"}

    expected_pages = (
        db.query(MaterialPage)
        .filter(MaterialPage.material_version_id == material.active_version_id)
        .count()
    )
    if expected_pages == 0:
        # V7.5.1-01: Fallback for very old materials without MaterialPage records.
        source = Path(settings.UPLOAD_DIR) / material.file_path
        if material.file_type.lower() == "pdf" and source.is_file():
            try:
                pdf = fitz.open(str(source))
                expected_pages = len(pdf)
                pdf.close()
            except Exception:
                pass
        if expected_pages == 0:
            return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "missing"}

    upload_dir = Path(settings.UPLOAD_DIR)
    assets = (
        db.query(MaterialPageAsset)
        .filter(
            MaterialPageAsset.material_version_id == material.active_version_id,
            MaterialPageAsset.render_status == "ready",
        )
        .all()
    )
    ready_pages = sum(1 for a in assets if _is_asset_valid(a, upload_dir))
    missing_pages = expected_pages - ready_pages

    if missing_pages == 0:
        status = "ready"
    elif ready_pages > 0:
        status = "partial"
    else:
        status = "missing"

    return {
        "expected_pages": expected_pages,
        "ready_pages": ready_pages,
        "missing_pages": missing_pages,
        "status": status,
    }


def ensure_active_page_assets(db: Session, material: Material) -> dict:
    """Check if the active version has complete page assets; rebuild if not.

    Returns a dict with ``expected_pages``, ``ready_pages``,
    ``missing_pages``, and ``status``.

    * ``ready`` – all pages have valid assets.
    * ``partial`` – some pages have assets; rebuild was attempted but
      either failed or could not cover every page.
    * ``missing`` – no page assets at all and rebuild failed.
    * ``not_applicable`` – non-PDF material.
    """
    if material.file_type.lower() != "pdf":
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "not_applicable"}

    current = _page_asset_status(db, material)
    if current["missing_pages"] == 0:
        return current

    # Attempt rebuild
    return rebuild_page_assets(db, material)


def rebuild_page_assets(db: Session, material: Material) -> dict:
    """Render the full PDF and atomically replace page assets for the active version.

    The rebuild is staged in a private directory.  Only on full success does
    the staging directory replace the version directory and the DB records
    get updated.  On failure, old data is preserved.
    """
    if material.file_type.lower() != "pdf":
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "not_applicable"}

    if not material.active_version_id:
        return {"expected_pages": 0, "ready_pages": 0, "missing_pages": 0, "status": "missing"}

    expected_pages = (
        db.query(MaterialPage)
        .filter(MaterialPage.material_version_id == material.active_version_id)
        .count()
    )
    source = Path(settings.UPLOAD_DIR) / material.file_path
    if not source.is_file():
        # Cannot rebuild without the source PDF
        return _page_asset_status(db, material)

    if expected_pages == 0:
        # V7.5.1-01: Fallback for very old materials without MaterialPage records.
        try:
            pdf = fitz.open(str(source))
            expected_pages = len(pdf)
            pdf.close()
        except Exception:
            return _page_asset_status(db, material)
        if expected_pages == 0:
            return _page_asset_status(db, material)

    version_id = material.active_version_id
    page_root = source.parent / "pages"
    staging_dir = page_root / f".v7-staging-rebuild-{material.id}-{version_id}-{uuid4().hex}"

    try:
        rendered = render_pdf_pages(source, staging_dir)
    except Exception as exc:
        logger.warning("Page-asset rebuild render failed for material %s: %s", material.id, exc)
        _cleanup_staging(staging_dir)
        return _page_asset_status(db, material)

    if len(rendered) != expected_pages:
        logger.warning(
            "Page-asset rebuild page count mismatch for material %s: expected %d, got %d",
            material.id, expected_pages, len(rendered),
        )
        _cleanup_staging(staging_dir)
        return _page_asset_status(db, material)

    # Promote staging to version directory
    version_dir = page_root / f"v{material.version}"
    if version_dir.exists():
        backup_dir = page_root / f".v7-backup-{material.id}-{version_id}-{uuid4().hex}"
        version_dir.replace(backup_dir)
    else:
        backup_dir = None

    try:
        staging_dir.replace(version_dir)
    except Exception as exc:
        logger.warning("Page-asset rebuild promote failed for material %s: %s", material.id, exc)
        # Restore backup
        if backup_dir is not None and backup_dir.exists():
            backup_dir.replace(version_dir)
        _cleanup_staging(staging_dir)
        return _page_asset_status(db, material)

    # Clean up backup
    if backup_dir is not None and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    # Atomically replace DB records for the active version
    upload_root = Path(settings.UPLOAD_DIR)
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
    db.commit()

    # Clean up old staging directories that may exist from failed prior runs
    for child in page_root.iterdir() if page_root.exists() else []:
        if child.name.startswith(".v7-staging-rebuild-"):
            shutil.rmtree(child, ignore_errors=True)

    return _page_asset_status(db, material)


def _cleanup_staging(staging_dir: Path) -> None:
    """Best-effort removal of a staging directory."""
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
