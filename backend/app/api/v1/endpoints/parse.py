"""Material parse, reader, image, and chunk endpoints."""
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response, status
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
from app.models.material_page import MaterialPage
from app.models.material_page_asset import MaterialPageAsset
from app.models.parse_job import ParseJob
from app.models.user import User
from app.schemas.material import ChunkListResponse, ChunkResponse, ParseResponse
from app.services.material_delete_service import delete_material as delete_material_service
from app.services.material_image_service import image_integrity, image_state, reextract_images
from app.services.parse_job_service import create_or_get_job, recover_stale_jobs

router = APIRouter()


def _get_owned_material(db: Session, material_id: int, user_id: int) -> Material:
    material = (
        db.query(Material)
        .filter(Material.id == material_id, Material.user_id == user_id)
        .first()
    )
    if material is None:
        raise NotFoundException(message="资料不存在")
    return material


def _safe_upload_path(relative_path: str) -> Path:
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
        .filter(
            MaterialImage.id == image_id,
            Material.user_id == current_user.id,
            MaterialImage.material_version_id == Material.active_version_id,
            MaterialImage.render_status == "ready",
        )
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


@router.post("/{material_id}/parse", response_model=ParseResponse)
def parse_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ParseResponse:
    material = _get_owned_material(db, material_id, current_user.id)
    create_or_get_job(db, material, current_user.id)
    return ParseResponse(material_id=material_id, status="processing", chunk_count=0)


@router.get("/{material_id}/image-integrity")
def get_image_integrity(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return image_integrity(db, _get_owned_material(db, material_id, current_user.id))


@router.post("/{material_id}/images/reextract")
def retry_image_extraction(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return reextract_images(db, _get_owned_material(db, material_id, current_user.id))


@router.post("/{material_id}/page-assets/rebuild")
def rebuild_page_assets_endpoint(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from app.services.material_page_asset_service import rebuild_page_assets

    return rebuild_page_assets(db, _get_owned_material(db, material_id, current_user.id))


@router.get("/{material_id}/parse-jobs")
def list_parse_jobs(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _get_owned_material(db, material_id, current_user.id)
    recover_stale_jobs(db)
    rows = (
        db.query(ParseJob)
        .filter(ParseJob.material_id == material_id, ParseJob.user_id == current_user.id)
        .order_by(ParseJob.id.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "status": row.status,
                "attempt": row.attempt,
                "started_at": row.started_at,
                "heartbeat_at": row.heartbeat_at,
                "error": row.error_message,
            }
            for row in rows
        ]
    }


@router.post("/{material_id}/parse-jobs/{job_id}/retry")
def retry_parse_job(
    material_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    material = _get_owned_material(db, material_id, current_user.id)
    old = (
        db.query(ParseJob)
        .filter(
            ParseJob.id == job_id,
            ParseJob.material_id == material_id,
            ParseJob.user_id == current_user.id,
        )
        .first()
    )
    if old is None:
        raise NotFoundException(message="解析任务不存在")
    if old.status in {"queued", "running"}:
        return {"job_id": old.id, "status": old.status}
    job = create_or_get_job(db, material, current_user.id)
    return {"job_id": job.id, "status": job.status}


@router.post("/{material_id}/parse-jobs/{job_id}/cancel")
def cancel_parse_job(
    material_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _get_owned_material(db, material_id, current_user.id)
    job = (
        db.query(ParseJob)
        .filter(
            ParseJob.id == job_id,
            ParseJob.material_id == material_id,
            ParseJob.user_id == current_user.id,
        )
        .first()
    )
    if job is None:
        raise NotFoundException(message="解析任务不存在")
    if job.status in {"queued", "running"}:
        job.status = "cancelled"
        job.cancellation_reason = "用户取消"
        job.finished_at = utc_now()
        db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/{material_id}/chunks", response_model=ChunkListResponse)
def list_chunks(
    material_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    include_decorative: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChunkListResponse:
    material = _get_owned_material(db, material_id, current_user.id)

    query = db.query(MaterialChunk).filter(
        MaterialChunk.material_id == material_id,
        MaterialChunk.is_active == 1,
    )
    if material.active_version_id is not None:
        query = query.filter(MaterialChunk.material_version_id == material.active_version_id)
    total = query.count()
    items = (
        query.order_by(MaterialChunk.chunk_index.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    from collections import defaultdict
    from app.schemas.material import ImageResponse

    page_nos = list({chunk.page_no for chunk in items if chunk.page_no})
    images_by_chunk: dict[int, list] = defaultdict(list)
    page_fallback_images: dict[int, list] = defaultdict(list)
    if page_nos and material.active_version_id is not None:
        image_query = db.query(MaterialImage).filter(
            MaterialImage.material_id == material_id,
            MaterialImage.material_version_id == material.active_version_id,
            MaterialImage.render_status == "ready",
            MaterialImage.page_no.in_(page_nos),
        )
        if not include_decorative:
            image_query = image_query.filter(MaterialImage.is_decorative == 0)
        for image in image_query.all():
            if image.chunk_id:
                images_by_chunk[image.chunk_id].append(image)
            else:
                page_fallback_images[image.page_no].append(image)

    first_chunk_for_page: dict[int, int] = {}
    for chunk in items:
        if chunk.page_no and chunk.page_no not in first_chunk_for_page:
            first_chunk_for_page[chunk.page_no] = chunk.id

    chunk_responses = []
    for chunk in items:
        chunk_dict = ChunkResponse.model_validate(chunk).model_dump()
        attached = images_by_chunk.get(chunk.id, [])
        if (
            not attached
            and chunk.page_no
            and first_chunk_for_page.get(chunk.page_no) == chunk.id
        ):
            attached = page_fallback_images.get(chunk.page_no, [])
        if attached:
            chunk_dict["images"] = [
                ImageResponse(
                    id=image.id,
                    page_no=image.page_no,
                    width=image.width,
                    height=image.height,
                    format=image.format,
                    file_url=f"/api/v1/materials/images/{image.id}/file",
                    is_decorative=bool(image.is_decorative),
                    decorative_reason=image.decorative_reason,
                    status=image_state(image)[0],
                    missing_reason=image_state(image)[1],
                    color_variance=image.color_variance,
                    coverage_ratio=image.coverage_ratio,
                )
                for image in attached
            ]
        chunk_responses.append(ChunkResponse(**chunk_dict))

    return ChunkListResponse(
        items=chunk_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{material_id}/pages")
def list_material_pages(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    material = _get_owned_material(db, material_id, current_user.id)
    query = db.query(MaterialPage).filter(MaterialPage.material_id == material.id)
    if material.active_version_id is not None:
        query = query.filter(MaterialPage.material_version_id == material.active_version_id)
    rows = query.order_by(MaterialPage.page_no).all()
    assets = {
        asset.page_no: asset
        for asset in db.query(MaterialPageAsset)
        .filter(
            MaterialPageAsset.material_id == material.id,
            MaterialPageAsset.material_version_id == material.active_version_id,
        )
        .all()
    }
    return {
        "items": [
            {
                "id": row.id,
                "page_no": row.page_no,
                "page_type": row.page_type,
                "parser_version": row.parser_version,
                "raw_text": row.raw_text or "",
                "clean_text": row.clean_text or "",
                "removed_lines": row.decisions_json or "[]",
                "blocks": row.blocks_json or "[]",
                "page_asset": (
                    {
                        "id": asset.id,
                        "file_url": f"/api/v1/materials/page-assets/{asset.id}/file",
                        "width": asset.width,
                        "height": asset.height,
                        "dpi": asset.dpi,
                        "sha256": asset.sha256,
                        "status": asset.render_status,
                        "error_code": asset.error_code,
                    }
                    if (asset := assets.get(row.page_no))
                    else None
                ),
            }
            for row in rows
        ]
    }


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    material = _get_owned_material(db, material_id, current_user.id)
    if material.status == "processing":
        raise BusinessException(message="资料处理中，暂不能删除，请稍后再试")
    delete_material_service(db, material)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
