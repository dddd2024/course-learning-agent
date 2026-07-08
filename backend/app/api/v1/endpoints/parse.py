"""Material parse and chunk query endpoints.

These endpoints live under ``/api/v1/materials`` (note: not under
``/courses``) so chunks can be addressed directly by ``material_id``.

* ``POST /materials/{material_id}/parse`` reads the uploaded file from
  disk, extracts text via :mod:`app.retrieval.parsers`, splits it with
  :mod:`app.retrieval.chunker`, persists chunks to ``material_chunks``,
  and updates the material's status (``processing`` -> ``ready`` or
  ``failed``).
* ``GET /materials/{material_id}/chunks`` returns paginated chunks.
* ``DELETE /materials/{material_id}`` removes the material, its chunks,
  its security findings, and the original uploaded file from disk.

All queries are scoped by ``current_user.id`` so a material owned by
another user is invisible (returned as 404).
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.schemas.material import (
    ChunkListResponse,
    ChunkResponse,
    ParseResponse,
)
from app.services.material_parser import parse_with_retry

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

    Delegates to :func:`app.services.material_parser.parse_with_retry`
    which owns the retry policy, status tracking, and error logging.
    """
    material = _get_owned_material(db, material_id, current_user.id)
    final_status, chunk_count = parse_with_retry(
        db, material, current_user.id
    )
    return ParseResponse(
        material_id=material_id,
        status=final_status,
        chunk_count=chunk_count,
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


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a material owned by the current user.

    Removes the material record, all of its chunks, its security findings,
    and the original uploaded file from disk. A material in ``processing``
    status cannot be deleted (returns 400) to avoid racing the parse flow.
    A missing disk file is treated as already-cleaned-up and does not
    cause the delete to fail.
    """
    material = _get_owned_material(db, material_id, current_user.id)

    if material.status == "processing":
        raise BusinessException(message="资料处理中，暂不能删除，请稍后再试")

    # Delete the original file from disk first. A missing file (already
    # removed, moved, etc.) must not fail the request.
    try:
        disk_path = Path(settings.UPLOAD_DIR) / material.file_path
        disk_path.unlink(missing_ok=True)
    except OSError:
        # Permission / path errors are logged by the global handler; the
        # database cleanup still proceeds so no orphan rows remain.
        pass

    # Delete dependent rows before the parent row.
    db.query(MaterialChunk).filter(
        MaterialChunk.material_id == material_id
    ).delete(synchronize_session=False)

    from app.models.security_finding import MaterialSecurityFinding

    db.query(MaterialSecurityFinding).filter(
        MaterialSecurityFinding.material_id == material_id
    ).delete(synchronize_session=False)

    db.delete(material)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
