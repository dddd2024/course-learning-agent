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
from app.models.parse_job import ParseJob
from app.services.material_page_asset_service import evaluate_page_asset_coverage


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
    expected_page_numbers = list(range(1, coverage["expected_pages"] + 1))
    ready_page_numbers = sorted(set(expected_page_numbers) - set(coverage["missing_page_numbers"]))
    file_type = (material.file_type or "").lower()
    reader_mode = "page" if file_type == "pdf" else "structured_text"

    blocking_reasons: list[str] = []
    if material.status != "ready":
        blocking_reasons.append(f"material_status:{material.status}")
    if version is None:
        blocking_reasons.append("active_version_missing")
    elif version.status != "ready":
        blocking_reasons.append(f"version_status:{version.status}")
    if job is None:
        blocking_reasons.append("parse_job_missing")
    elif job.status != "succeeded":
        blocking_reasons.append(f"parse_job_status:{job.status}")

    is_scanned_pdf = file_type == "pdf" and not nonempty_chunks
    if file_type == "pdf":
        if coverage["status"] != "ready":
            blocking_reasons.append("page_assets_incomplete")
        if not is_scanned_pdf:
            if not nonempty_chunks:
                blocking_reasons.append("active_chunks_missing")
            elif fts_error:
                blocking_reasons.append(fts_error)
            elif fts_count != len(indexable_chunks):
                blocking_reasons.append("fts_index_incomplete")
    elif not nonempty_chunks:
        blocking_reasons.append("active_chunks_missing")
    elif fts_error:
        blocking_reasons.append(fts_error)
    elif fts_count != len(indexable_chunks):
        blocking_reasons.append("fts_index_incomplete")

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
        "material_page_count": coverage["expected_pages"],
        "expected_page_numbers": expected_page_numbers,
        "ready_page_numbers": ready_page_numbers,
        "missing_page_numbers": coverage["missing_page_numbers"],
        "fts_indexed_chunk_count": fts_count,
        "reader_mode": reader_mode,
        "usable": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
    }
