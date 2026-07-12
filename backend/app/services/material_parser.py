"""Material parse service with bounded retry.

Extracted from the parse endpoint so the retry policy, status tracking,
and error logging live in one place. The endpoint keeps doing auth +
ownership checks and returns the response; this service owns the parse
state machine.

State machine
-------------
uploaded -> parse requested -> processing
  - success                          -> ready   (parse_attempts reset)
  - retryable error, attempts < max  -> processing (retry)
  - retryable error, attempts == max -> failed  (error log written)
  - non-retryable error              -> failed  (error log written)

Re-parse of a ready material:
  - success -> ready (new chunks)
  - failure with old chunks -> stays ready + warning + error log
  - failure with no old chunks -> failed + error log
"""
from __future__ import annotations

import logging
import hashlib
import json
import shutil
import time
from uuid import uuid4
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import utc_now
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.material_page import MaterialPage
from app.models.security_finding import MaterialSecurityFinding
from app.retrieval.chunker import clean_keyword_text
from app.retrieval.semantic_chunker import semantic_chunk_document
from app.retrieval.parsers import parse_file
from app.retrieval.search import update_fts_index
from app.services.material_cleaner import clean_pages
from app.services.document_cleaning_pipeline import clean_document_pages
from app.services import security_scanner
from app.services.chunk_quality import evaluate_chunks_quality
from app.services.error_logger import log_error

logger = logging.getLogger(__name__)

MAX_PARSE_RETRIES = 3
RETRY_DELAYS_SECONDS = (0, 2, 5)  # course-project-friendly; not too slow

# Errors that mean "retrying won't help" — fail immediately.
_NON_RETRYABLE_HINTS = ("unsupported file type", "file not found", "permission")


class ParseCancelled(Exception):
    """Internal control-flow signal: do not activate a partial parse."""


def _is_retryable(exc: Exception) -> bool:
    """Heuristic: retry on parser/runtime errors, not on config errors."""
    msg = (str(exc) or "").lower()
    return not any(h in msg for h in _NON_RETRYABLE_HINTS)


def _count_existing_chunks(db: Session, material_id: int) -> int:
    return (
        db.query(MaterialChunk)
        .filter(MaterialChunk.material_id == material_id)
        .count()
    )


def _remove_staged_images(staging_dir: Path | None, *, promoted: bool = False) -> None:
    """Remove only a parser-created staging directory under UPLOAD_DIR."""
    if staging_dir is None or not staging_dir.exists():
        return
    try:
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        staging_path = staging_dir.resolve()
        is_parser_staging = staging_path.name.startswith(".v7-staging-")
        is_uncommitted_version = promoted and staging_path.name.startswith("v")
        if staging_path.is_relative_to(upload_root) and (is_parser_staging or is_uncommitted_version):
            shutil.rmtree(staging_path)
    except Exception:
        logger.warning("Could not clean staged images at %s", staging_dir, exc_info=True)


def parse_with_retry(
    db: Session,
    material: Material,
    user_id: int,
    *,
    max_retries: int = MAX_PARSE_RETRIES,
    parse_fn: Callable[[str, str], list] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[str, int]:
    """Run the parse with bounded retry.

    Returns ``(final_status, chunk_count)``. Writes an error_log row on
    every failed attempt (warning level while retries remain, error level
    once exhausted). Mutates ``material`` status / parse_* fields.

    ``parse_fn`` / ``sleep_fn`` are injectable for tests. When
    ``parse_fn`` is ``None`` the current ``parse_file`` module attribute
    is used (so tests can monkeypatch ``app.services.material_parser.parse_file``).
    """
    if parse_fn is None:
        parse_fn = parse_file
    sleep = sleep_fn or time.sleep
    material_id = material.id
    existing_chunk_count = _count_existing_chunks(db, material_id)
    staged_image_dir: Path | None = None
    promoted_image_dir: Path | None = None

    def check_cancelled() -> None:
        if is_cancelled is not None and is_cancelled():
            raise ParseCancelled()

    material.status = "processing"
    material.error_message = None
    # Preserve the parse_started_at set by the parse endpoint so the
    # frontend elapsed timer and the timeout clock both start from when
    # the user requested the parse (not when the background task began).
    # Only set it as a defensive fallback if the endpoint never did.
    if material.parse_started_at is None:
        material.parse_started_at = utc_now()
    material.parse_attempts = 0
    db.commit()

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        material.parse_attempts = attempt
        db.commit()
        try:
            check_cancelled()  # before reading source
            file_path = Path(settings.UPLOAD_DIR) / material.file_path
            pages = parse_fn(str(file_path), material.file_type)
            check_cancelled()  # after parser
            # V7.4-02 P1-02: Single cleaning pass.
            # clean_document_pages calls clean_pages internally; do not
            # call clean_pages separately here (was causing double cleaning).
            cleaned_pages = clean_document_pages(pages)
            chunks = semantic_chunk_document(cleaned_pages)
            check_cancelled()  # before creating a staging version

            # Preserve old evidence: a successful parse creates a new
            # immutable version and only the active version participates in
            # new retrieval.  This keeps old citations and quizzes readable.
            content_hash = hashlib.sha256(
                "\n".join(str(c.get("text", "")) for c in chunks).encode("utf-8")
            ).hexdigest()
            existing_version = db.query(MaterialVersion).filter(
                MaterialVersion.material_id == material_id,
                MaterialVersion.content_hash == content_hash,
                MaterialVersion.status == "ready",
            ).first()
            if existing_version is not None:
                check_cancelled()  # do not switch an existing version after cancellation
                # Collect old active chunk ids before deactivating so we
                # can update the FTS index after the commit.
                old_chunk_ids = [
                    row.id for row in db.query(MaterialChunk).filter(
                        MaterialChunk.material_id == material_id,
                        MaterialChunk.is_active == 1,
                    ).all()
                ]
                db.query(MaterialChunk).filter(MaterialChunk.material_id == material_id).update(
                    {MaterialChunk.is_active: 0}, synchronize_session=False
                )
                db.query(MaterialChunk).filter(MaterialChunk.material_version_id == existing_version.id).update(
                    {MaterialChunk.is_active: 1}, synchronize_session=False
                )
                # Collect re-activated chunk ids for FTS update.
                reactivated_ids = [
                    row.id for row in db.query(MaterialChunk).filter(
                        MaterialChunk.material_version_id == existing_version.id,
                        MaterialChunk.is_active == 1,
                    ).all()
                ]
                material.active_version_id = existing_version.id
                material.version = existing_version.version
                material.status = "ready"
                material.parse_finished_at = utc_now()
                material.parse_attempts = 0
                db.commit()
                # V6-60: Update FTS index AFTER the commit so a failure
                # here does not roll back the chunk data.  The call
                # removes old (now-inactive) chunks and inserts the
                # re-activated ones in a single pass.
                try:
                    update_fts_index(db, old_chunk_ids + reactivated_ids)
                except Exception as fts_exc:
                    logger.warning("FTS index update failed for material %s: %s", material_id, fts_exc)
                return "ready", _count_existing_chunks(db, material_id)
            next_version = (db.query(MaterialVersion.version).filter(
                MaterialVersion.material_id == material_id
            ).order_by(MaterialVersion.version.desc()).first() or (0,))[0] + 1
            version_row = MaterialVersion(
                material_id=material_id, version=next_version,
                status="processing", content_hash=content_hash,
            )
            db.add(version_row)
            db.flush()
            # Preserve page/block provenance before semantic chunks are built.
            for page, cleaned in zip(pages, clean_results):
                raw = page.text
                db.add(MaterialPage(material_id=material_id, material_version_id=version_row.id, page_no=page.page_no, page_type=page.page_type, parser_version=page.parser_version, raw_text=raw, clean_text=cleaned.text, blocks_json=json.dumps([block.to_dict() for block in page.blocks], ensure_ascii=False), decisions_json=json.dumps(cleaned.decisions, ensure_ascii=False)))
            check_cancelled()  # before writing chunks
            # Collect old active chunk ids before deactivating so we can
            # update the FTS index after the commit.
            old_chunk_ids_new = [
                row.id for row in db.query(MaterialChunk).filter(
                    MaterialChunk.material_id == material_id,
                    MaterialChunk.is_active == 1,
                ).all()
            ]
            db.query(MaterialChunk).filter(MaterialChunk.material_id == material_id).update(
                {MaterialChunk.is_active: 0}, synchronize_session=False
            )
            # Security findings are version-dependent and must not point to
            # chunks that are being replaced in the active view.
            db.query(MaterialSecurityFinding).filter(
                MaterialSecurityFinding.material_id == material_id
            ).delete(synchronize_session=False)

            saved_chunks: list[MaterialChunk] = []
            # Step 1: Rule-based pre-filter (fast, no API calls)
            candidate_chunks = chunks

            # Step 2: AI quality evaluation (batch LLM call)
            eval_input = [
                {"text": c["text"], "index": i}
                for i, c in enumerate(candidate_chunks)
            ]
            quality_results = evaluate_chunks_quality(eval_input)

            # Step 3: Store with quality scores
            for i, chunk in enumerate(candidate_chunks):
                raw_text = chunk["text"]
                text = raw_text.strip()
                if not text:
                    text = raw_text.strip()
                qr = quality_results[i] if i < len(quality_results) else {"quality": 0.5, "reason": ""}
                # LEARN-V3-01: persist noise_flags as JSON so the UI can
                # show why a chunk was filtered out of retrieval.
                noise_flags = chunk.get("noise_flags")
                noise_flags_json = (
                    json.dumps(noise_flags, ensure_ascii=False)
                    if noise_flags
                    else None
                )
                mc = MaterialChunk(
                    material_id=material_id,
                    material_version_id=version_row.id,
                    course_id=material.course_id,
                    chunk_index=chunk["chunk_index"],
                    title=chunk.get("title"),
                    page_no=chunk.get("page_start"),
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                    source_block_ids_json=json.dumps(chunk.get("source_block_ids", []), ensure_ascii=False),
                    source_fragments_json=json.dumps(chunk.get("source_fragments_json", []), ensure_ascii=False),
                    split_reason=chunk.get("split_reason"),
                    chunker_version=chunk.get("chunker_version"),
                    text=text,
                    raw_text=raw_text,
                    cleaner_version="v1",
                    noise_score=0.0 if chunk.get("is_indexable", True) else 1.0,
                    is_indexable=1 if chunk.get("is_indexable", True) else 0,
                    stable_key=f"{material_id}:{chunk.get('page_start') or 0}:{hashlib.sha256(' '.join(text.split()).encode('utf-8')).hexdigest()[:24]}",
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    is_active=1,
                    # ``token_count`` is kept for legacy clients; it now
                    # means an explicit approximation rather than chars.
                    char_count=len(text),
                    estimated_token_count=max(1, (len(text.encode("utf-8")) + 3) // 4),
                    token_count=max(1, (len(text.encode("utf-8")) + 3) // 4),
                    keyword_text=clean_keyword_text(text),
                    quality_score=qr.get("quality", 0.5),
                    quality_reason=qr.get("reason", ""),
                    noise_flags=noise_flags_json,
                )
                db.add(mc)
                saved_chunks.append(mc)

            db.flush()

            check_cancelled()  # before image extraction / indexing

            # --- Image extraction (PDF only) ---
            if material.file_type.lower() == "pdf":
                try:
                    from app.services.material_image_service import reextract_images
                    image_root = (Path(settings.UPLOAD_DIR) / material.file_path).parent / "images"
                    staged_image_dir = image_root / f".v7-staging-{material_id}-{next_version}-{uuid4().hex}"
                    # A failed extraction must not leak its delete/insert
                    # statements into the parse transaction.
                    with db.begin_nested():
                        reextract_images(
                            db,
                            material,
                            image_dir=staged_image_dir,
                            commit=False,
                        )
                    logger.info("Refreshed images for material %s", material_id)
                except Exception as img_exc:
                    _remove_staged_images(staged_image_dir)
                    staged_image_dir = None
                    logger.warning("Image extraction failed for material %s: %s", material_id, img_exc)

            check_cancelled()  # do not publish staged images after cancellation

            for f in security_scanner.scan_material_chunks(saved_chunks):
                db.add(f)

            check_cancelled()  # immediately before active-version switch

            if staged_image_dir is not None and staged_image_dir.exists():
                promoted_image_dir = staged_image_dir.parent / f"v{next_version}"
                if promoted_image_dir.exists():
                    raise RuntimeError(f"图片版本目录已存在：{promoted_image_dir.name}")
                staged_image_dir.replace(promoted_image_dir)
                relative_root = Path(settings.UPLOAD_DIR)
                for image in db.query(MaterialImage).filter(
                    MaterialImage.material_id == material_id
                ).all():
                    image.image_path = str(
                        (promoted_image_dir / image.image_filename).relative_to(relative_root)
                    ).replace("\\", "/")
                staged_image_dir = None

            check_cancelled()  # after file promotion, before the atomic DB switch

            material.status = "ready"
            version_row.status = "ready"
            version_row.parsed_at = utc_now()
            material.active_version_id = version_row.id
            material.version = next_version
            material.error_message = None
            material.last_parse_error = None
            material.parse_attempts = 0  # reset on success
            material.parse_finished_at = utc_now()
            db.commit()
            # V6-60: Incrementally update the FTS index AFTER the commit
            # so that a failure here does not roll back the chunk data.
            # ``update_fts_index`` with both old and new chunk IDs removes
            # the now-inactive old chunks and inserts the new active ones
            # in a single pass.
            all_affected_ids = old_chunk_ids_new + [c.id for c in saved_chunks]
            if all_affected_ids:
                try:
                    update_fts_index(db, all_affected_ids)
                except Exception as fts_exc:
                    logger.warning("FTS index update failed for material %s: %s", material_id, fts_exc)
            return "ready", len(chunks)
        except ParseCancelled:
            db.rollback()
            _remove_staged_images(staged_image_dir)
            _remove_staged_images(promoted_image_dir, promoted=True)
            material = db.query(Material).filter(Material.id == material_id).first()
            if material is not None:
                material.status = "ready" if existing_chunk_count else "uploaded"
                material.parse_finished_at = utc_now()
                material.last_parse_error = "解析已取消"
                material.error_message = None
                db.commit()
            return "cancelled", 0
        except Exception as exc:  # noqa: BLE001 - any parse failure
            db.rollback()
            _remove_staged_images(staged_image_dir)
            _remove_staged_images(promoted_image_dir, promoted=True)
            material = (
                db.query(Material)
                .filter(Material.id == material_id)
                .first()
            )
            last_exc = exc
            attempts_so_far = attempt
            # Write a warning log for this attempt (still retrying) unless
            # this is the last attempt or the error is non-retryable.
            is_last = attempt >= max_retries or not _is_retryable(exc)
            log_error(
                db,
                user_id,
                category="parse",
                level="error" if is_last else "warning",
                title="资料解析失败",
                message=(
                    f"「{material.filename}」第 {attempt}/{max_retries} 次解析失败："
                    f"{str(exc) or exc.__class__.__name__}"
                ),
                technical_detail=f"{exc.__class__.__name__}: {exc}",
                course_id=material.course_id,
                material_id=material_id,
                retry_count=attempts_so_far,
                max_retries=max_retries,
            )
            if is_last:
                break
            # Sleep before the next retry (skip on attempt 1's 0s delay).
            delay = RETRY_DELAYS_SECONDS[min(attempt, len(RETRY_DELAYS_SECONDS) - 1)]
            if delay > 0:
                sleep(delay)

    # All retries exhausted (or non-retryable): finalize the failure.
    material = db.query(Material).filter(Material.id == material_id).first()
    material.parse_finished_at = utc_now()
    err_msg = str(last_exc) or (
        last_exc.__class__.__name__ if last_exc else "解析失败"
    )
    material.last_parse_error = err_msg

    if existing_chunk_count > 0:
        # Keep the old chunks usable; surface a stale-ready warning.
        material.status = "ready"
        material.error_message = (
            f"最近一次重新解析失败，已保留上一版解析结果：{err_msg}"
        )
        db.commit()
        return "ready", existing_chunk_count

    material.status = "failed"
    material.error_message = err_msg
    db.commit()
    return "failed", 0
