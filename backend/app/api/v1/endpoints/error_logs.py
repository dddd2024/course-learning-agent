"""Agent error log endpoint (Phase 2 Task E).

``GET /api/v1/agent-error-logs`` returns paginated error logs for the
current user. All queries are scoped by ``current_user.id`` so cross-user
access is impossible.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.error_log import AgentErrorLog
from app.models.user import User
from app.schemas.error_log import (
    AgentErrorLogListResponse,
    AgentErrorLogResponse,
)

router = APIRouter()


@router.get(
    "",
    response_model=AgentErrorLogListResponse,
)
def list_error_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentErrorLogListResponse:
    """List agent error logs for the current user (newest first)."""
    query = db.query(AgentErrorLog).filter(
        AgentErrorLog.user_id == current_user.id
    )
    total = query.count()
    items = (
        query.order_by(AgentErrorLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return AgentErrorLogListResponse(
        items=[AgentErrorLogResponse.model_validate(i) for i in items],
        total=total,
    )
