"""Material upload and list endpoints.

All queries are scoped by ``current_user.id`` to enforce per-user data
isolation. A course owned by another user is invisible (returned as 404)
so existence is never leaked.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.models.course import Course
from app.models.material import Material
from app.models.user import User
from app.schemas.material import MaterialListResponse, MaterialResponse

router = APIRouter()

ALLOWED_FILE_TYPES = {"txt", "pdf", "docx", "pptx", "md"}


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
    """Upload a material file to a course owned by the current user."""
    _get_owned_course(db, course_id, current_user.id)

    filename = file.filename or ""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_FILE_TYPES:
        raise BusinessException(message="不支持的文件类型")

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
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
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(content)

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
    """
    _get_owned_course(db, course_id, current_user.id)

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
