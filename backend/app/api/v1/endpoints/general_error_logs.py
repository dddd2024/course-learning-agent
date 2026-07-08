"""General error log center endpoints.

``GET  /logs``          paginated, filterable list (current user only)
``GET  /logs/{id}``     single log detail (current user only)
``POST /logs/{id}/resolve``  mark a log resolved/ignored

All queries are scoped by ``current_user.id`` so cross-user access is
impossible (404, no existence leak).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.models.general_error_log import ErrorLog
from app.models.user import User
from app.schemas.general_error_log import (
    ErrorLogListResponse,
    ErrorLogResolveRequest,
    ErrorLogResponse,
)

router = APIRouter()

_VALID_STATUSES = {"open", "resolved", "ignored"}


def _get_owned_log(db: Session, log_id: int, user_id: int) -> ErrorLog:
    log = (
        db.query(ErrorLog)
        .filter(ErrorLog.id == log_id, ErrorLog.user_id == user_id)
        .first()
    )
    if log is None:
        raise NotFoundException(message="日志不存在")
    return log


@router.get("", response_model=ErrorLogListResponse)
def list_logs(
    category: str | None = Query(None, max_length=30),
    level: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=20),
    material_id: int | None = Query(None),
    agent_run_id: int | None = Query(None),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ErrorLogListResponse:
    """List the current user's error logs, newest first.

    Optional filters: category, level, status, material_id, agent_run_id,
    keyword (matches title/message).
    """
    query = db.query(ErrorLog).filter(ErrorLog.user_id == current_user.id)
    if category:
        query = query.filter(ErrorLog.category == category)
    if level:
        query = query.filter(ErrorLog.level == level)
    if status:
        query = query.filter(ErrorLog.status == status)
    if material_id is not None:
        query = query.filter(ErrorLog.material_id == material_id)
    if agent_run_id is not None:
        query = query.filter(ErrorLog.agent_run_id == agent_run_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (ErrorLog.title.like(like)) | (ErrorLog.message.like(like))
        )

    total = query.count()
    items = (
        query.order_by(ErrorLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ErrorLogListResponse(
        items=[ErrorLogResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{log_id}", response_model=ErrorLogResponse)
def get_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ErrorLogResponse:
    """Return a single log's full detail (including technical_detail)."""
    log = _get_owned_log(db, log_id, current_user.id)
    return ErrorLogResponse.model_validate(log)


@router.post("/{log_id}/resolve", response_model=ErrorLogResponse)
def resolve_log(
    log_id: int,
    body: ErrorLogResolveRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ErrorLogResponse:
    """Mark a log as resolved (or ignored).

    Default status is ``resolved``; pass ``{"status": "ignored"}`` to
    dismiss a log without addressing it.
    """
    log = _get_owned_log(db, log_id, current_user.id)
    new_status = (body.status if body else "resolved") or "resolved"
    if new_status not in _VALID_STATUSES:
        raise BusinessException(
            message=f"无效的日志状态：{new_status}，允许 open/resolved/ignored"
        )
    if new_status == "open":
        raise BusinessException(message="不能将日志重置为 open")
    log.status = new_status
    db.commit()
    db.refresh(log)
    return ErrorLogResponse.model_validate(log)
