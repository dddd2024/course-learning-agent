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
import time
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import utc_now
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.security_finding import MaterialSecurityFinding
from app.retrieval.chunker import build_chunks, clean_keyword_text, clean_material_text
from app.retrieval.parsers import parse_file
from app.services import security_scanner
from app.services.chunk_quality import evaluate_chunks_quality
from app.services.error_logger import log_error

logger = logging.getLogger(__name__)

MAX_PARSE_RETRIES = 3
RETRY_DELAYS_SECONDS = (0, 2, 5)  # course-project-friendly; not too slow

# Errors that mean "retrying won't help" — fail immediately.
_NON_RETRYABLE_HINTS = ("unsupported file type", "file not found", "permission")


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


def parse_with_retry(
    db: Session,
    material: Material,
    user_id: int,
    *,
    max_retries: int = MAX_PARSE_RETRIES,
    parse_fn: Callable[[str, str], list] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
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
            file_path = Path(settings.UPLOAD_DIR) / material.file_path
            pages = parse_fn(str(file_path), material.file_type)
            chunks = build_chunks(pages, chunk_size=600, overlap=100)

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
                db.query(MaterialChunk).filter(MaterialChunk.material_id == material_id).update(
                    {MaterialChunk.is_active: 0}, synchronize_session=False
                )
                db.query(MaterialChunk).filter(MaterialChunk.material_version_id == existing_version.id).update(
                    {MaterialChunk.is_active: 1}, synchronize_session=False
                )
                material.active_version_id = existing_version.id
                material.version = existing_version.version
                material.status = "ready"
                material.parse_finished_at = utc_now()
                material.parse_attempts = 0
                db.commit()
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
                text = clean_material_text(raw_text) or clean_material_text(raw_text.replace("\n", " "))
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
                    page_no=chunk.get("page_no"),
                    text=text,
                    raw_text=raw_text,
                    cleaner_version="v1",
                    noise_score=0.0 if chunk.get("is_indexable", True) else 1.0,
                    is_indexable=1 if chunk.get("is_indexable", True) else 0,
                    stable_key=f"{material_id}:{chunk.get('page_no') or 0}:{hashlib.sha256(' '.join(text.split()).encode('utf-8')).hexdigest()[:24]}",
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

            # --- Image extraction (PDF only) ---
            if material.file_type.lower() == "pdf":
                try:
                    from app.retrieval.image_extractor import extract_images_from_pdf
                    from app.models.material_image import MaterialImage

                    db.query(MaterialImage).filter(
                        MaterialImage.material_id == material_id
                    ).delete(synchronize_session=False)

                    file_path_obj = Path(settings.UPLOAD_DIR) / material.file_path
                    extracted = extract_images_from_pdf(str(file_path_obj))

                    page_to_chunk = {}
                    for mc in saved_chunks:
                        if mc.page_no:
                            page_to_chunk.setdefault(mc.page_no, mc.id)

                    img_dir = Path(settings.UPLOAD_DIR) / material.file_path.replace(
                        f"original.{material.file_type}", ""
                    ) / "images"
                    img_dir.mkdir(parents=True, exist_ok=True)

                    seen_image_hashes: set[str] = set()
                    for idx, img in enumerate(extracted):
                        if img.perceptual_hash in seen_image_hashes:
                            continue
                        seen_image_hashes.add(img.perceptual_hash or "")
                        img_filename = f"page{img.page_no}_{idx}.{img.format}"
                        img_full_path = img_dir / img_filename
                        img_full_path.write_bytes(img.image_bytes)

                        rel_path = str(img_full_path.relative_to(Path(settings.UPLOAD_DIR))).replace("\\", "/")

                        db.add(MaterialImage(
                            material_id=material_id,
                            course_id=material.course_id,
                            chunk_id=page_to_chunk.get(img.page_no),
                            page_no=img.page_no,
                            image_filename=img_filename,
                            image_path=rel_path,
                            width=img.width,
                            height=img.height,
                            format=img.format,
                            is_decorative=1 if img.is_decorative else 0,
                            decorative_reason=img.decorative_reason,
                            perceptual_hash=img.perceptual_hash,
                            color_variance=img.color_variance,
                            coverage_ratio=img.coverage_ratio,
                        ))
                    db.flush()
                    logger.info("Saved %d images for material %s", len(extracted), material_id)
                except Exception as img_exc:
                    logger.warning("Image extraction failed for material %s: %s", material_id, img_exc)

            for f in security_scanner.scan_material_chunks(saved_chunks):
                db.add(f)

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
            return "ready", len(chunks)
        except Exception as exc:  # noqa: BLE001 - any parse failure
            db.rollback()
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
