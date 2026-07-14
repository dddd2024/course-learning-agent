"""Material parse and chunk query endpoints.

These endpoints live under ``/api/v1/materials`` (note: not under
``/courses``) so chunks can be addressed directly by ``material_id``.

* ``POST /materials/{material_id}/parse`` creates a queued
  :class:`ParseJob` and returns immediately with ``status=processing``.
  A persistent ``ParseWorker`` process polls the DB, claims the job,
  and runs the actual parse with heartbeat + retry.
* ``GET /materials/{material_id}/chunks`` returns paginated chunks.
* ``DELETE /materials/{material_id}`` removes the material, its chunks,
  its security findings, and the original uploaded file from disk.

All queries are scoped by ``current_user.id`` so a material owned by
another user is invisible (returned as 404).
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Query, Response, status
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
from app.services.parse_job_service import create_or_get_job, recover_stale_jobs
from app.models.parse_job import ParseJob
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.services.material_delete_service import delete_material as delete_material_service
from app.services.material_image_service import image_integrity, image_state, reextract_images
from app.services.material_readiness_service import material_readiness
from app.services.material_page_catalog_service import build_material_page_catalog
from app.services.material_identity_service import resolve_owned_material
from app.services.page_asset_rebuild_contract import normalize_page_asset_rebuild_result

router = APIRouter()


def _get_owned_material(
    db: Session, material_id: str | int, user_id: int
) -> Material:
    """Return the material if it belongs to ``user_id``, else 404.

    Scoping by ``user_id`` ensures cross-user access returns 404 rather
    than 403 so existence is never leaked.
    """
    material = resolve_owned_material(db, material_id, user_id)
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
    material_id: str,
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


@router.get("/page-assets/{asset_id}/file")
def get_material_page_asset_file(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Return an active-version page image without leaking another user's asset."""
    asset = (
        db.query(MaterialPageAsset)
        .join(Material, Material.id == MaterialPageAsset.material_id)
        .filter(
            MaterialPageAsset.id == asset_id,
            Material.user_id == current_user.id,
            Material.active_version_id == MaterialPageAsset.material_version_id,
            MaterialPageAsset.render_status == "ready",
        )
        .first()
    )
    if asset is None or not asset.asset_path:
        raise NotFoundException(message="页面资源不存在")
    path = _safe_upload_path(asset.asset_path)
    if not path.is_file():
        raise NotFoundException(message="页面资源不存在")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        filename=path.name,
        headers={"ETag": f'"{asset.sha256}"'} if asset.sha256 else None,
    )


@router.post(
    "/{material_id}/parse",
    response_model=ParseResponse,
)
def parse_material(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ParseResponse:
    """Create a queued ParseJob and return ``processing`` immediately.

    V6-50: The API only creates the job; a persistent ``ParseWorker``
    process polls the DB and runs the actual parse.  If the material
    already has an active job, the existing job is returned without
    creating a duplicate.
    """
    material = _get_owned_material(db, material_id, current_user.id)
    create_or_get_job(db, material, current_user.id)

    return ParseResponse(
        material_id=material.id,
        status="processing",
        chunk_count=0,
    )


@router.get("/{material_id}/readiness")
def get_material_readiness(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the complete reader-readiness contract for the active version."""
    return material_readiness(db, _get_owned_material(db, material_id, current_user.id))


@router.get("/{material_id}/image-integrity")
def get_image_integrity(material_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    return image_integrity(db, _get_owned_material(db, material_id, current_user.id))


@router.post("/{material_id}/images/reextract")
def retry_image_extraction(material_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    return reextract_images(db, _get_owned_material(db, material_id, current_user.id))


@router.post("/{material_id}/page-assets/rebuild")
def rebuild_page_assets_endpoint(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_e2e_inject_page_backfill_failure: str | None = Header(default=None),
) -> dict:
    """Rebuild page-level visual assets for an existing PDF material.

    V7.5.1-01: Allows the frontend to repair materials that were parsed
    before page rendering was introduced, without re-uploading or
    re-parsing the file.
    """
    from app.services.material_page_asset_service import rebuild_page_assets
    material = _get_owned_material(db, material_id, current_user.id)
    inject_failure = settings.E2E_MODE and x_e2e_inject_page_backfill_failure == "true"
    result = rebuild_page_assets(db, material, inject_backfill_failure=inject_failure)
    return normalize_page_asset_rebuild_result(material.id, result)


@router.get("/{material_id}/parse-jobs")
def list_parse_jobs(material_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    material = _get_owned_material(db, material_id, current_user.id)
    recover_stale_jobs(db)
    rows = db.query(ParseJob).filter(ParseJob.material_id == material.id, ParseJob.user_id == current_user.id).order_by(ParseJob.id.desc()).all()
    return {"items": [{"id": row.id, "status": row.status, "attempt": row.attempt, "started_at": row.started_at, "heartbeat_at": row.heartbeat_at, "error": row.error_message} for row in rows]}


@router.post("/{material_id}/parse-jobs/{job_id}/retry")
def retry_parse_job(material_id: str, job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    material = _get_owned_material(db, material_id, current_user.id)
    old = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.material_id == material.id, ParseJob.user_id == current_user.id).first()
    if old is None:
        raise NotFoundException(message="解析任务不存在")
    if old.status in {"queued", "running"}:
        return {"job_id": old.id, "status": old.status}
    job = create_or_get_job(db, material, current_user.id)
    return {"job_id": job.id, "status": job.status}


@router.post("/{material_id}/parse-jobs/{job_id}/cancel")
def cancel_parse_job(material_id: str, job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    material = _get_owned_material(db, material_id, current_user.id)
    job = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.material_id == material.id, ParseJob.user_id == current_user.id).first()
    if job is None:
        raise NotFoundException(message="解析任务不存在")
    if job.status in {"queued", "running"}:
        job.status, job.cancellation_reason, job.finished_at = "cancelled", "用户取消", utc_now()
        db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get(
    "/{material_id}/chunks",
    response_model=ChunkListResponse,
)
def list_chunks(
    material_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    include_decorative: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChunkListResponse:
    """Return paginated chunks for a material owned by the current user."""
    material = _get_owned_material(db, material_id, current_user.id)

    query = db.query(MaterialChunk).filter(
        MaterialChunk.material_id == material.id,
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
        image_query = db.query(MaterialImage).filter(
            MaterialImage.material_id == material.id,
            MaterialImage.page_no.in_(page_nos),
        )
        if material.active_version_id:
            # V7.5.1-04: Only return images for the active version, but
            # also include legacy images that have no version_id (NULL).
            image_query = image_query.filter(
                (MaterialImage.material_version_id == material.active_version_id)
                | (MaterialImage.material_version_id.is_(None))
            )
        if not include_decorative:
            image_query = image_query.filter(MaterialImage.is_decorative == 0)
        imgs = image_query.all()
        for img in imgs:
            if img.chunk_id:
                images_by_chunk[img.chunk_id].append(img)
            else:
                page_fallback_images[img.page_no].append(img)

    chunk_responses = []
    for c in items:
        chunk_dict = ChunkResponse.model_validate(c).model_dump()
        chunk_dict["content"] = c.text
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
                    is_decorative=bool(img.is_decorative),
                    decorative_reason=img.decorative_reason,
                    status=image_state(img)[0], missing_reason=image_state(img)[1], color_variance=img.color_variance,
                    coverage_ratio=img.coverage_ratio,
                ) for img in attached
            ]
        chunk_responses.append(ChunkResponse(**chunk_dict))

    return ChunkListResponse(
        items=chunk_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{material_id}/pages")
def list_material_pages(material_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    """Reader contract: page catalogue plus raw/clean text and decisions."""
    material = _get_owned_material(db, material_id, current_user.id)
    return build_material_page_catalog(db, material)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_material(
    material_id: str,
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

    delete_material_service(db, material)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
