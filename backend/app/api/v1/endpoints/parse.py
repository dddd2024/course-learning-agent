"""Material parse and chunk query endpoints.

These endpoints live under ``/api/v1/materials`` (note: not under
``/courses``) so chunks can be addressed directly by ``material_id``.

* ``POST /materials/{material_id}/parse`` sets the material to
  ``processing`` and schedules a background task that runs
  :func:`app.services.material_parser.parse_with_retry`. The endpoint
  returns immediately with ``status=processing`` so the frontend is not
  blocked; the background task eventually flips the status to ``ready``
  or ``failed``.
* ``GET /materials/{material_id}/chunks`` returns paginated chunks.
* ``DELETE /materials/{material_id}`` removes the material, its chunks,
  its security findings, and the original uploaded file from disk.

All queries are scoped by ``current_user.id`` so a material owned by
another user is invisible (returned as 404).
"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.core.timezone import utc_now
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.user import User
from app.schemas.material import (
    ChunkListResponse,
    ChunkResponse,
    ParseResponse,
)
from app.services.error_logger import log_error
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


def _safe_upload_path(relative_path: str) -> Path:
    """Resolve a DB path and refuse paths escaping the upload root."""
    root = Path(settings.UPLOAD_DIR).resolve()
    candidate = (root / relative_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise NotFoundException(message="文件不存在")
    return candidate


@router.get("/{material_id}/file")
def get_material_file(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    material = _get_owned_material(db, material_id, current_user.id)
    path = _safe_upload_path(material.file_path)
    if not path.is_file():
        raise NotFoundException(message="文件不存在")
    return FileResponse(path, filename=material.filename)


@router.get("/images/{image_id}/file")
def get_material_image_file(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    image = (
        db.query(MaterialImage)
        .join(Material, Material.id == MaterialImage.material_id)
        .filter(MaterialImage.id == image_id, Material.user_id == current_user.id)
        .first()
    )
    if image is None:
        raise NotFoundException(message="图片不存在")
    path = _safe_upload_path(image.image_path)
    if not path.is_file():
        raise NotFoundException(message="图片不存在")
    return FileResponse(path, filename=image.image_filename)


def _run_parse_in_background(material_id: int, user_id: int) -> None:
    """Background task: run parse_with_retry with an independent session.

    Stability Task A: the background task must NOT reuse the request-level
    ``db`` Session (which is closed after the response). Instead it creates
    its own session via :data:`app.core.database.SessionLocal` and closes
    it in a ``finally`` block. Any exception is caught so a material can
    never get stuck in ``processing`` — it is flipped to ``failed`` and a
    ``category=parse`` error log is written.
    """
    # Import lazily so tests can monkeypatch ``app.core.database.SessionLocal``.
    from app.core.database import SessionLocal

    db = SessionLocal()
    material = None
    try:
        material = (
            db.query(Material)
            .filter(Material.id == material_id, Material.user_id == user_id)
            .first()
        )
        if material is None:
            return
        parse_with_retry(db, material, user_id)
    except Exception as exc:
        # Fallback: prevent the material from staying in processing forever.
        db.rollback()
        material = (
            db.query(Material)
            .filter(Material.id == material_id, Material.user_id == user_id)
            .first()
        )
        if material is not None:
            material.status = "failed"
            material.error_message = "后台解析任务异常，请查看日志中心"
            material.last_parse_error = str(exc)
            material.parse_finished_at = utc_now()
            log_error(
                db,
                user_id,
                category="parse",
                level="error",
                title="后台解析任务异常",
                message=str(exc),
                technical_detail=f"{exc.__class__.__name__}: {exc}",
                course_id=material.course_id,
                material_id=material.id,
                retry_count=material.parse_attempts or 0,
                max_retries=3,
                commit=False,
            )
            db.commit()
    finally:
        db.close()


@router.post(
    "/{material_id}/parse",
    response_model=ParseResponse,
)
def parse_material(
    material_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ParseResponse:
    """Schedule a background parse task and return ``processing`` immediately.

    If the material is already ``processing``, returns the current status
    without scheduling a duplicate task. The actual parse (with retry)
    runs in the background via :class:`fastapi.BackgroundTasks`.
    """
    material = _get_owned_material(db, material_id, current_user.id)

    if material.status == "processing":
        return ParseResponse(
            material_id=material_id,
            status="processing",
            chunk_count=0,
        )

    # Set processing state so the immediate response is accurate and
    # list_materials sees the material as in-progress.
    material.status = "processing"
    material.error_message = None
    material.parse_started_at = utc_now()
    material.parse_attempts = 0
    db.commit()

    background_tasks.add_task(
        _run_parse_in_background, material_id, current_user.id
    )

    return ParseResponse(
        material_id=material_id,
        status="processing",
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
        MaterialChunk.material_id == material_id,
        MaterialChunk.is_active == 1,
    )
    total = query.count()
    items = (
        query.order_by(MaterialChunk.chunk_index.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Load images associated with these chunks' pages
    from collections import defaultdict
    from app.models.material_image import MaterialImage
    from app.schemas.material import ImageResponse

    page_nos = list(set(c.page_no for c in items if c.page_no))
    images_by_chunk: dict[int, list] = defaultdict(list)
    page_fallback_images: dict[int, list] = defaultdict(list)
    if page_nos:
        imgs = db.query(MaterialImage).filter(
            MaterialImage.material_id == material_id,
            MaterialImage.page_no.in_(page_nos),
            MaterialImage.is_decorative == 0,
        ).all()
        for img in imgs:
            if img.chunk_id:
                images_by_chunk[img.chunk_id].append(img)
            else:
                page_fallback_images[img.page_no].append(img)

    chunk_responses = []
    for c in items:
        chunk_dict = ChunkResponse.model_validate(c).model_dump()
        attached = images_by_chunk.get(c.id, [])
        # Legacy page-only images are attached once, to the first visible
        # chunk on that page; never repeated across every chunk on a page.
        if not attached and c.page_no and c.page_no in page_fallback_images and next((x for x in items if x.page_no == c.page_no), None) == c:
            attached = page_fallback_images[c.page_no]
        if attached:
            chunk_dict["images"] = [
                ImageResponse(
                    id=img.id, page_no=img.page_no, width=img.width,
                    height=img.height, format=img.format,
                    file_url=f"/api/v1/materials/images/{img.id}/file",
                ) for img in attached
            ]
        chunk_responses.append(ChunkResponse(**chunk_dict))

    return ChunkListResponse(
        items=chunk_responses,
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
