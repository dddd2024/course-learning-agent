"""Material upload and list endpoints.

All queries are scoped by ``current_user.id`` to enforce per-user data
isolation. A course owned by another user is invisible (returned as 404)
so existence is never leaked.
"""
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.core.timezone import utc_now
from app.models.course import Course
from app.models.material import Material
from app.models.user import User
from app.schemas.material import MaterialListResponse, MaterialResponse
from app.services.error_logger import log_error

router = APIRouter()

ALLOWED_FILE_TYPES = {"txt", "pdf", "docx", "pptx", "md"}

# A parse task stuck in ``processing`` longer than this is considered
# timed out (e.g. the worker crashed mid-parse). list_materials flips
# such rows to ``failed`` and writes an error_log so the user can retry.
PARSE_TIMEOUT_SECONDS = 300


def _get_owned_course(db: Session, course_id: int, user_id: int) -> Course:
    """Return the course if it belongs to ``user_id``, else 404.

    Centralises the user-scoped lookup so isolation is consistent across
    upload / list.
    """
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user_id)
        .first()
    )
    if course is None:
        raise NotFoundException(message="课程不存在")
    return course


def _recover_timed_out_materials(db: Session, user_id: int) -> None:
    """Flip processing materials past the timeout to ``failed`` + error_log.

    A parse task can get stuck in ``processing`` if the worker crashes
    mid-parse or the process is killed. Without recovery, the material
    stays ``processing`` forever and the user cannot re-parse it. This
    helper runs before list_materials returns so the UI always reflects
    a recoverable state.

    Only materials owned by ``user_id`` are touched (per-user isolation).
    """
    threshold = utc_now() - timedelta(seconds=PARSE_TIMEOUT_SECONDS)
    stuck = (
        db.query(Material)
        .filter(
            Material.user_id == user_id,
            Material.status == "processing",
            Material.parse_started_at.isnot(None),
            Material.parse_started_at < threshold,
        )
        .all()
    )
    for mat in stuck:
        mat.status = "failed"
        mat.parse_finished_at = utc_now()
        err = (
            f"解析任务超时（>{PARSE_TIMEOUT_SECONDS}s 未完成），"
            "可重新解析；若仍失败请检查文件大小或格式。"
        )
        mat.last_parse_error = err
        mat.error_message = err
        log_error(
            db,
            user_id,
            category="parse",
            level="error",
            title="资料解析超时",
            message=err,
            technical_detail=(
                f"parse_started_at={mat.parse_started_at.isoformat()} "
                f"timeout_seconds={PARSE_TIMEOUT_SECONDS}"
            ),
            course_id=mat.course_id,
            material_id=mat.id,
            retry_count=mat.parse_attempts or 0,
            max_retries=3,
            commit=False,
        )
    if stuck:
        db.commit()


@router.post(
    "/{course_id}/materials",
    response_model=MaterialResponse,
    status_code=201,
)
async def upload_material(
    course_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialResponse:
    """Upload a material file to a course owned by the current user.

    On any failure (unsupported type, oversized, disk write error) an
    ErrorLog(category=upload) row is written so the user can see the
    reason in the log center. Disk write failures also roll back the
    Material row to avoid orphan records with empty file_path.
    """
    _get_owned_course(db, course_id, current_user.id)

    filename = file.filename or ""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_FILE_TYPES:
        log_error(
            db,
            current_user.id,
            category="upload",
            level="error",
            title="资料上传失败",
            message=f"不支持的文件类型：{ext or '(无扩展名)'}",
            technical_detail=f"filename={filename} ext={ext}",
            course_id=course_id,
        )
        raise BusinessException(message="不支持的文件类型")

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        log_error(
            db,
            current_user.id,
            category="upload",
            level="error",
            title="资料上传失败",
            message=(
                f"文件大小超过限制：{len(content) / 1024 / 1024:.1f}MB "
                f"> {settings.MAX_UPLOAD_MB}MB"
            ),
            technical_detail=f"filename={filename} size={len(content)}",
            course_id=course_id,
        )
        raise BusinessException(message="文件大小超过限制")

    # The material_id is only known after the row is persisted, so create
    # the record first with a placeholder path, then save the file to its
    # final location and update file_path with the relative storage path.
    material = Material(
        user_id=current_user.id,
        course_id=course_id,
        filename=filename,
        file_type=ext,
        file_path="",
        status="uploaded",
        version=1,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    relative_path = (
        Path(str(current_user.id))
        / str(course_id)
        / str(material.id)
        / f"original.{ext}"
    )
    absolute_path = Path(settings.UPLOAD_DIR) / relative_path

    try:
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(content)
    except OSError as exc:
        # Disk write failed: roll back the Material row so no orphan with
        # empty file_path remains, then log the error.
        db.delete(material)
        db.commit()
        log_error(
            db,
            current_user.id,
            category="upload",
            level="error",
            title="资料上传失败",
            message="文件保存到磁盘失败，请稍后重试或联系管理员",
            technical_detail=f"{exc.__class__.__name__}: {exc}",
            course_id=course_id,
        )
        raise BusinessException(message="上传失败，请查看日志中心")

    material.file_path = str(relative_path).replace("\\", "/")
    db.commit()
    db.refresh(material)

    return MaterialResponse.model_validate(material)


@router.get(
    "/{course_id}/materials",
    response_model=MaterialListResponse,
)
def list_materials(
    course_id: int,
    type: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialListResponse:
    """List materials for a course owned by the current user.

    Optional ``type`` and ``status`` query parameters filter by file
    extension (e.g. ``txt``) and processing status respectively.

    Before returning, any ``processing`` material past the parse timeout
    is flipped to ``failed`` and an error_log is written, so the UI never
    shows a forever-processing row.
    """
    _get_owned_course(db, course_id, current_user.id)
    _recover_timed_out_materials(db, current_user.id)

    query = db.query(Material).filter(
        Material.course_id == course_id,
        Material.user_id == current_user.id,
    )
    if type:
        query = query.filter(Material.file_type == type)
    if status:
        query = query.filter(Material.status == status)

    items = query.order_by(Material.id.desc()).all()
    return MaterialListResponse(
        items=[MaterialResponse.model_validate(m) for m in items],
        total=len(items),
    )
