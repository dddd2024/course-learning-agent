"""Canonical page catalogue for a material's active version.

The reader must not infer page availability from only ``MaterialPage`` rows:
older parsed PDFs can have complete rendered assets but no persisted page
records.  This module centralises the version-scoped page-number facts used by
the API, readiness calculation and repair workflow.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.material import Material
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset


def _valid_numbers(values: list[int | None]) -> set[int]:
    return {value for value in values if isinstance(value, int) and value > 0}


def _pdf_page_numbers(material: Material) -> list[int]:
    if (material.file_type or "").lower() != "pdf":
        return []
    source = Path(settings.UPLOAD_DIR) / material.file_path
    if not source.is_file():
        return []
    try:
        with fitz.open(str(source)) as pdf:
            return list(range(1, len(pdf) + 1))
    except Exception:
        return []


def resolve_expected_page_numbers(db: Session, material: Material) -> dict:
    """Resolve the active-version reader page set and its diagnostics.

    A readable PDF uses its actual page count as the boundary.  When the
    source is unavailable (the legacy recovery case), persisted page and asset
    numbers form the best available catalogue.  Numbers outside an available
    PDF boundary stay visible as diagnostics, never as phantom reader pages.
    """
    if not material.active_version_id:
        return {
            "expected_page_numbers": [], "pdf_page_numbers": [],
            "persisted_page_numbers": [], "asset_page_numbers": [],
            "invalid_page_numbers": [], "extra_page_numbers": [],
            "duplicate_page_numbers": [], "duplicate_asset_page_numbers": [],
        }

    version_id = material.active_version_id
    page_rows = db.query(MaterialPage.page_no).filter(
        MaterialPage.material_id == material.id,
        MaterialPage.material_version_id == version_id,
    ).all()
    asset_rows = db.query(MaterialPageAsset.page_no).filter(
        MaterialPageAsset.material_id == material.id,
        MaterialPageAsset.material_version_id == version_id,
    ).all()
    raw_pages = [row[0] for row in page_rows]
    raw_assets = [row[0] for row in asset_rows]
    persisted = _valid_numbers(raw_pages)
    assets = _valid_numbers(raw_assets)
    pdf_pages = _pdf_page_numbers(material)
    boundary = set(pdf_pages)
    union = persisted | assets | boundary
    expected = boundary if boundary else union
    invalid = sorted({value for value in raw_pages + raw_assets if not isinstance(value, int) or value <= 0})
    extras = sorted((persisted | assets) - expected) if boundary else []
    page_counts = Counter(value for value in raw_pages if isinstance(value, int) and value > 0)
    asset_counts = Counter(value for value in raw_assets if isinstance(value, int) and value > 0)
    return {
        "expected_page_numbers": sorted(expected),
        "pdf_page_numbers": pdf_pages,
        "persisted_page_numbers": sorted(persisted),
        "asset_page_numbers": sorted(assets),
        "invalid_page_numbers": invalid,
        "extra_page_numbers": extras,
        "duplicate_page_numbers": sorted(value for value, count in page_counts.items() if count > 1),
        "duplicate_asset_page_numbers": sorted(value for value, count in asset_counts.items() if count > 1),
    }


def build_material_page_catalog(db: Session, material: Material) -> dict:
    """Return the API-ready active-version catalogue without fabricating IDs."""
    facts = resolve_expected_page_numbers(db, material)
    version_id = material.active_version_id
    if not version_id:
        return {**facts, "items": [], "expected_pages": 0, "persisted_pages": 0, "asset_pages": 0,
                "effective_pages": 0, "missing_catalog_page_numbers": [], "synthetic_page_numbers": []}

    rows = db.query(MaterialPage).filter(
        MaterialPage.material_id == material.id,
        MaterialPage.material_version_id == version_id,
    ).order_by(MaterialPage.page_no, MaterialPage.id).all()
    assets = db.query(MaterialPageAsset).filter(
        MaterialPageAsset.material_id == material.id,
        MaterialPageAsset.material_version_id == version_id,
    ).order_by(MaterialPageAsset.page_no, MaterialPageAsset.id).all()
    pages_by_no: dict[int, list[MaterialPage]] = defaultdict(list)
    assets_by_no: dict[int, list[MaterialPageAsset]] = defaultdict(list)
    for row in rows:
        if row.page_no and row.page_no > 0:
            pages_by_no[row.page_no].append(row)
    for asset in assets:
        if asset.page_no and asset.page_no > 0:
            assets_by_no[asset.page_no].append(asset)

    expected = facts["expected_page_numbers"]
    items = []
    synthetic = []
    missing_catalog = []
    for page_no in expected:
        page = pages_by_no.get(page_no, [None])[0]
        asset = assets_by_no.get(page_no, [None])[0]
        is_synthetic = page is None
        if is_synthetic:
            synthetic.append(page_no)
        if page is None and asset is None:
            missing_catalog.append(page_no)
        asset_payload = None
        if asset is not None:
            asset_payload = {
                "id": asset.id,
                "file_url": f"/api/v1/materials/page-assets/{asset.id}/file",
                "width": asset.width, "height": asset.height, "dpi": asset.dpi,
                "sha256": asset.sha256, "status": asset.render_status,
                "error_code": asset.error_code,
            }
        items.append({
            "catalog_key": f"material:{material.id}:version:{version_id}:page:{page_no}",
            "id": page.id if page is not None else None,
            "page_no": page_no,
            "page_type": page.page_type if page is not None else "unknown",
            "parser_version": page.parser_version if page is not None else None,
            "raw_text": (page.raw_text or "") if page is not None else "",
            "clean_text": (page.clean_text or "") if page is not None else "",
            "removed_lines": (page.decisions_json or "[]") if page is not None else "[]",
            "blocks": (page.blocks_json or "[]") if page is not None else "[]",
            "is_synthetic": is_synthetic,
            "page_asset": asset_payload,
        })
    return {
        **facts,
        "material_id": material.id,
        "material_version_id": version_id,
        "expected_pages": len(expected),
        "persisted_pages": len(set(facts["persisted_page_numbers"]) & set(expected)),
        "asset_pages": len(set(facts["asset_page_numbers"]) & set(expected)),
        "effective_pages": len(items),
        "missing_catalog_page_numbers": missing_catalog,
        "synthetic_page_numbers": synthetic,
        "items": items,
    }
