"""Stable public contract for page-asset rebuild responses.

The rebuild service historically returned raw coverage dictionaries from a
few early-exit paths. Public API callers must receive one shape regardless
of the internal failure phase so the frontend cannot mistake readable legacy
assets for a completed repair.
"""
from __future__ import annotations

from typing import Any


_STABLE_KEYS = {"reader_state", "page_asset_rebuild", "page_catalog_backfill"}


def normalize_page_asset_rebuild_result(
    material_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Return the stable rebuild contract for both new and legacy results."""
    normalized = dict(result)
    normalized.setdefault("material_id", material_id)

    if _STABLE_KEYS.issubset(normalized):
        normalized.setdefault("error_code", None)
        return normalized

    raw_status = str(normalized.get("status") or "failed")
    ready_pages = max(int(normalized.get("ready_pages") or 0), 0)
    expected_pages = max(int(normalized.get("expected_pages") or 0), ready_pages)
    raw_missing = normalized.get("missing_pages")
    missing_pages = max(
        int(raw_missing) if raw_missing is not None else expected_pages - ready_pages,
        0,
    )

    readable = ready_pages > 0
    if raw_status == "busy":
        asset_status = "skipped"
        error_code = "PAGE_ASSET_REBUILD_BUSY"
    elif raw_status == "not_applicable":
        asset_status = "skipped"
        error_code = "PAGE_ASSET_REBUILD_NOT_APPLICABLE"
    elif raw_status in {"ready", "partial"}:
        asset_status = "failed"
        error_code = "PAGE_ASSET_REBUILD_INCOMPLETE"
    else:
        asset_status = "failed"
        error_code = "PAGE_ASSET_REBUILD_FAILED"

    return {
        **normalized,
        "material_id": material_id,
        "status": "readable_but_not_repaired" if readable else "failed",
        "reader_state": "synthetic_fallback" if readable else "unavailable",
        "expected_pages": expected_pages,
        "ready_pages": ready_pages,
        "missing_pages": missing_pages,
        "page_asset_rebuild": {"status": asset_status},
        "page_catalog_backfill": {
            "status": "skipped",
            "created": 0,
            "remaining_synthetic_page_numbers": list(
                normalized.get("synthetic_page_numbers") or []
            ),
        },
        "error_code": error_code,
    }
