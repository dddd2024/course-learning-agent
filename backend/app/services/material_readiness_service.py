"""Machine-readable reader readiness for a material's active version.

The material status is deliberately not used as a proxy for reader
availability.  This service only aggregates persisted facts; it never repairs
or mutates parsing data.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_page import MaterialPage
from app.models.material_image import MaterialImage
from app.models.parse_job import ParseJob
from app.services.material_page_asset_service import evaluate_page_asset_coverage
from app.services.material_page_catalog_service import build_material_page_catalog


def _fts_count(db: Session, chunk_ids: list[int]) -> tuple[int, str | None]:
    """Count the active chunks that have actually reached SQLite FTS."""
    if not chunk_ids:
        return 0, None
    try:
        placeholders = ", ".join(f":chunk_{index}" for index in range(len(chunk_ids)))
        params = {f"chunk_{index}": value for index, value in enumerate(chunk_ids)}
        value = db.execute(
            text(f"SELECT COUNT(*) FROM material_chunks_fts WHERE chunk_id IN ({placeholders})"),
            params,
        ).scalar_one()
        return int(value), None
    except Exception as exc:  # table absent/unavailable must remain observable
        return 0, f"fts_unavailable:{type(exc).__name__}"


def material_readiness(db: Session, material: Material) -> dict:
    """Return reader readiness facts and explicit blocking reasons."""
    version = None
    if material.active_version_id:
        version = db.get(MaterialVersion, material.active_version_id)

    chunks = []
    if version is not None:
        chunks = db.query(MaterialChunk).filter(
            MaterialChunk.material_id == material.id,
            MaterialChunk.material_version_id == version.id,
            MaterialChunk.is_active == 1,
        ).all()
    nonempty_chunks = [chunk for chunk in chunks if (chunk.text or "").strip()]
    indexable_chunks = [chunk for chunk in nonempty_chunks if chunk.is_indexable]
    fts_count, fts_error = _fts_count(db, [chunk.id for chunk in indexable_chunks])

    # Jobs created for a first parse predate the first MaterialVersion, so
    # their FK can be null in databases produced before this contract.  The
    # active material is still the sole owner boundary; report the persisted
    # job version separately instead of pretending no completed job exists.
    job = db.query(ParseJob).filter(ParseJob.material_id == material.id).order_by(ParseJob.id.desc()).first()
    coverage = evaluate_page_asset_coverage(db, material)
    catalog = build_material_page_catalog(db, material)
    # Compatibility for an unavailable source plus a legacy coverage probe.
    # Production coverage and catalogue share the resolver; this preserves an
    # observable boundary when an older integration supplies only counts.
    if not catalog["expected_page_numbers"] and coverage.get("expected_pages", 0):
        fallback = list(range(1, int(coverage["expected_pages"]) + 1))
        catalog.update({
            "expected_page_numbers": fallback, "expected_pages": len(fallback),
            "effective_pages": len(fallback), "persisted_pages": 0,
            "asset_pages": len(fallback) - len(coverage.get("missing_page_numbers", [])),
            "missing_catalog_page_numbers": [], "synthetic_page_numbers": fallback,
        })
    expected_page_numbers = catalog["expected_page_numbers"]
    ready_page_numbers = sorted(set(expected_page_numbers) - set(coverage["missing_page_numbers"]))
    file_type = (material.file_type or "").lower()
    reader_mode = "page" if file_type == "pdf" else "structured_text"

    base_reader_reasons: list[str] = []
    if material.status != "ready":
        base_reader_reasons.append(f"material_status:{material.status}")
    if version is None:
        base_reader_reasons.append("active_version_missing")
    elif version.status != "ready":
        base_reader_reasons.append(f"version_status:{version.status}")

    active_pages = []
    if version is not None:
        active_pages = db.query(MaterialPage).filter(
            MaterialPage.material_id == material.id,
            MaterialPage.material_version_id == version.id,
        ).all()
    raw_text_chars = sum(len((page.raw_text or "").strip()) for page in active_pages)
    image_only_ratio = (
        sum(1 for page in active_pages if page.page_type == "image_only") / len(active_pages)
        if active_pages else 0.0
    )
    document_mode = "non_pdf_text"
    if file_type == "pdf":
        if not catalog["expected_pages"]:
            document_mode = "unknown_pdf"
        elif nonempty_chunks:
            document_mode = "text_pdf"
        elif (image_only_ratio >= 0.8 or not active_pages) and raw_text_chars < 40:
            document_mode = "scanned_pdf"
        elif raw_text_chars > 0 or active_pages:
            document_mode = "unexpected_empty_text_pdf"
        else:
            document_mode = "unknown_pdf"
    warnings: list[str] = []
    if catalog["synthetic_page_numbers"]:
        warnings.append("legacy_page_rows_missing")
    if document_mode == "scanned_pdf":
        warnings.append("structured_text_unavailable")
    if document_mode == "unknown_pdf":
        warnings.append("pdf_extraction_evidence_unavailable")
    page_assets_complete = False
    page_catalog_consistent = True
    if file_type == "pdf":
        page_assets_complete = coverage["status"] == "ready"
        page_catalog_consistent = (
            catalog["effective_pages"] == catalog["expected_pages"]
            and not catalog["missing_catalog_page_numbers"]
            and not catalog["duplicate_page_numbers"]
            and not catalog["duplicate_asset_page_numbers"]
            and not catalog["extra_page_numbers"]
        )
    available_modes: list[str] = []
    if file_type == "pdf" and page_assets_complete and page_catalog_consistent:
        available_modes.append("page")
    if nonempty_chunks:
        available_modes.append("structured_text")
    if raw_text_chars > 0:
        available_modes.append("raw")

    reader_blocking_reasons = list(base_reader_reasons)
    if not available_modes:
        if file_type == "pdf" and not page_assets_complete:
            reader_blocking_reasons.append("page_assets_incomplete")
        if not nonempty_chunks and raw_text_chars <= 0:
            reader_blocking_reasons.append("active_chunks_missing")
            reader_blocking_reasons.append("reader_content_missing")
    preferred_mode = (
        "page" if "page" in available_modes
        else "structured_text" if "structured_text" in available_modes
        else "raw" if "raw" in available_modes
        else None
    )
    reader_mode = preferred_mode or reader_mode

    assistant_reasons: list[str] = []
    assistant_usable = bool(nonempty_chunks) and not base_reader_reasons
    if not nonempty_chunks:
        assistant_reasons.append("active_chunks_missing")
    if assistant_usable:
        if fts_error:
            assistant_reasons.append(fts_error)
        elif fts_count != len(indexable_chunks):
            assistant_reasons.append("fts_index_incomplete")
    assistant_degraded = assistant_usable and bool(assistant_reasons)

    telemetry_warnings: list[str] = []
    if job is None:
        telemetry_warnings.append("parse_job_missing")
    elif job.status != "succeeded":
        telemetry_warnings.append(f"parse_job_status:{job.status}")

    page_status = "not_applicable"
    if file_type == "pdf":
        page_status = "ready" if page_assets_complete else (
            "partial" if ready_page_numbers else "missing"
        )
    image_query = db.query(MaterialImage).filter(MaterialImage.material_id == material.id)
    if version is not None:
        image_query = image_query.filter(
            (MaterialImage.material_version_id == version.id)
            | (MaterialImage.material_version_id.is_(None))
        )
    image_rows = image_query.all()
    standalone_image_status = "not_applicable" if not image_rows else (
        "ready" if all(row.render_status == "ready" for row in image_rows) else "missing"
    )
    repair_actions: list[str] = []
    if file_type == "pdf" and not page_assets_complete:
        repair_actions.append("rebuild_page_assets")
    if assistant_degraded:
        repair_actions.append("rebuild_fts")

    return {
        "material_id": material.id,
        "status": material.status,
        "active_version_id": material.active_version_id,
        "version_status": version.status if version else None,
        "file_type": file_type,
        "parse_job_status": job.status if job else None,
        "parse_job_version_id": job.material_version_id if job else None,
        "parse_error": (job.error_message if job else None) or material.last_parse_error,
        "active_chunk_count": len(nonempty_chunks),
        "indexable_chunk_count": len(indexable_chunks),
        "material_page_count": catalog["persisted_pages"],
        "expected_page_numbers": expected_page_numbers,
        "ready_page_numbers": ready_page_numbers,
        "missing_page_numbers": coverage["missing_page_numbers"],
        "fts_indexed_chunk_count": fts_count,
        "reader_mode": reader_mode,
        "document_mode": document_mode,
        "expected_page_count": catalog["expected_pages"],
        "persisted_page_count": catalog["persisted_pages"],
        "asset_page_count": catalog["asset_pages"],
        "effective_page_count": catalog["effective_pages"],
        "page_catalog_missing_numbers": catalog["missing_catalog_page_numbers"],
        "page_catalog_synthetic_numbers": catalog["synthetic_page_numbers"],
        "page_asset_missing_numbers": coverage["missing_page_numbers"],
        "page_asset_invalid_numbers": coverage.get("invalid_page_numbers", []),
        "page_catalog_consistent": page_catalog_consistent,
        "page_assets_complete": page_assets_complete,
        "warnings": warnings,
        "capabilities": {
            "reader": {
                "usable": not reader_blocking_reasons,
                "preferred_mode": preferred_mode,
                "available_modes": available_modes,
                "blocking_reasons": reader_blocking_reasons,
            },
            "assistant": {
                "usable": assistant_usable,
                "degraded": assistant_degraded,
                "retrieval_mode": "keyword_fallback" if assistant_degraded else "fts_bm25",
                "reasons": assistant_reasons,
            },
            "assets": {
                "page_status": page_status,
                "expected_pages": catalog["expected_pages"],
                "ready_pages": len(ready_page_numbers),
                "standalone_image_status": standalone_image_status,
                "document_readable": not reader_blocking_reasons,
            },
        },
        "reader": {
            "usable": not reader_blocking_reasons,
            "preferred_mode": preferred_mode,
            "available_modes": available_modes,
            "blocking_reasons": reader_blocking_reasons,
        },
        "assistant": {
            "usable": assistant_usable,
            "degraded": assistant_degraded,
            "retrieval_mode": "keyword_fallback" if assistant_degraded else "fts_bm25",
            "reasons": assistant_reasons,
        },
        "assets": {
            "page_status": page_status,
            "expected_pages": catalog["expected_pages"],
            "ready_pages": len(ready_page_numbers),
            "standalone_image_status": standalone_image_status,
            "document_readable": not reader_blocking_reasons,
        },
        "telemetry_warnings": telemetry_warnings,
        "repair": {"needed": bool(repair_actions), "actions": repair_actions},
        # Compatibility fields stay reader-scoped during the transition.
        "usable": not reader_blocking_reasons,
        "blocking_reasons": reader_blocking_reasons,
    }
