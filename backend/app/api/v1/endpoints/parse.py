"""Material parse and chunk query endpoints.

These endpoints live under ``/api/v1/materials`` (note: not under
``/courses``) so chunks can be addressed directly by ``material_id``.

* ``POST /materials/{material_id}/parse`` reads the uploaded file from
  disk, extracts text via :mod:`app.retrieval.parsers`, splits it with
  :mod:`app.retrieval.chunker`, persists chunks to ``material_chunks``,
  and updates the material's status (``processing`` -> ``ready`` or
  ``failed``).
* ``GET /materials/{material_id}/chunks`` returns paginated chunks.

All queries are scoped by ``current_user.id`` so a material owned by
another user is invisible (returned as 404).
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.retrieval.chunker import build_chunks, clean_keyword_text
from app.retrieval.parsers import parse_file
from app.schemas.material import (
    ChunkListResponse,
    ChunkResponse,
    ParseResponse,
)

router = APIRouter()


def _get_owned_material(
    db: Session, material_id: int, user_id: int
) -> Material:
    """Return the material if it belongs to ``user_id``, else 404.

    Scoping by ``user_id`` ensures cross-user access returns 404 rather
    than 403 so existence is never leaked.
    """
    material = (
        db.query(Material)
        .filter(Material.id == material_id, Material.user_id == user_id)
        .first()
    )
    if material is None:
        raise NotFoundException(message="资料不存在")
    return material


@router.post(
    "/{material_id}/parse",
    response_model=ParseResponse,
)
def parse_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ParseResponse:
    """Parse a material, build chunks, and update its status.

    The flow is: mark ``processing`` -> parse file -> build chunks ->
    replace any existing chunks -> mark ``ready``. On any exception the
    material is marked ``failed`` with the error message and an empty
    chunk list is reported back.
    """
    material = _get_owned_material(db, material_id, current_user.id)

    material.status = "processing"
    material.error_message = None
    db.commit()

    try:
        file_path = Path(settings.UPLOAD_DIR) / material.file_path
        pages = parse_file(str(file_path), material.file_type)
        chunks = build_chunks(pages, chunk_size=600, overlap=100)

        # Re-parsing replaces previous chunks so the operation is idempotent.
        db.query(MaterialChunk).filter(
            MaterialChunk.material_id == material_id
        ).delete(synchronize_session=False)

        # Also clear previous security findings (idempotent re-parse).
        from app.models.security_finding import MaterialSecurityFinding

        db.query(MaterialSecurityFinding).filter(
            MaterialSecurityFinding.material_id == material_id
        ).delete(synchronize_session=False)

        saved_chunks: list[MaterialChunk] = []
        for chunk in chunks:
            text = chunk["text"]
            mc = MaterialChunk(
                material_id=material_id,
                course_id=material.course_id,
                chunk_index=chunk["chunk_index"],
                title=chunk.get("title"),
                page_no=chunk.get("page_no"),
                text=text,
                token_count=len(text),
                keyword_text=clean_keyword_text(text),
            )
            db.add(mc)
            saved_chunks.append(mc)

        db.flush()  # populate chunk ids for the scanner

        # Phase 2 Task D: scan chunks for prompt-injection patterns.
        from app.services.security_scanner import scan_material_chunks

        findings = scan_material_chunks(saved_chunks)
        for f in findings:
            db.add(f)

        material.status = "ready"
        material.error_message = None
        db.commit()

        return ParseResponse(
            material_id=material_id,
            status="ready",
            chunk_count=len(chunks),
        )
    except Exception as exc:  # noqa: BLE001 - record any parse failure
        material.status = "failed"
        material.error_message = str(exc) or exc.__class__.__name__
        db.commit()
        return ParseResponse(
            material_id=material_id,
            status="failed",
            chunk_count=0,
        )


@router.get(
    "/{material_id}/chunks",
    response_model=ChunkListResponse,
)
def list_chunks(
    material_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChunkListResponse:
    """Return paginated chunks for a material owned by the current user."""
    _get_owned_material(db, material_id, current_user.id)

    query = db.query(MaterialChunk).filter(
        MaterialChunk.material_id == material_id
    )
    total = query.count()
    items = (
        query.order_by(MaterialChunk.chunk_index.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ChunkListResponse(
        items=[ChunkResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )
