"""Chunks endpoint — fetch a single chunk's full text (Phase 2 Task A).

``GET /api/v1/chunks/{chunk_id}`` returns the chunk text and its
material metadata. Ownership is verified through the
``chunk -> material -> course -> user_id`` chain so cross-user access
returns 404 (existence is never leaked).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.course import Course
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.schemas.chunk import ChunkDetailResponse

router = APIRouter()


def _get_owned_chunk(
    db: Session, chunk_id: int, user_id: int
) -> tuple[MaterialChunk, Material]:
    """Return ``(chunk, material)`` if the chunk belongs to ``user_id``.

    The ownership chain is:
    chunk -> material -> course -> user_id.
    We join through ``Material.course_id`` (the canonical owner link)
    rather than ``MaterialChunk.course_id`` so the check follows the
    real ownership path: a chunk exists only because its material
    belongs to a course owned by the user.
    """
    row = (
        db.query(MaterialChunk, Material)
        .join(Material, Material.id == MaterialChunk.material_id)
        .join(Course, Course.id == Material.course_id)
        .filter(MaterialChunk.id == chunk_id, Course.user_id == user_id)
        .first()
    )
    if row is None:
        raise NotFoundException(message="片段不存在")
    return row[0], row[1]


@router.get(
    "/{chunk_id}",
    response_model=ChunkDetailResponse,
)
def get_chunk(
    chunk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChunkDetailResponse:
    """Fetch a single chunk with its material metadata."""
    chunk, material = _get_owned_chunk(db, chunk_id, current_user.id)
    return ChunkDetailResponse(
        chunk_id=chunk.id,
        material_id=chunk.material_id,
        material_name=material.filename,
        title=chunk.title,
        page_no=chunk.page_no,
        text=chunk.text or "",
    )
