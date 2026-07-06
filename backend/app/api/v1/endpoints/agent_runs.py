"""Agent-run audit read endpoints.

``GET /api/v1/agent-runs`` lists the current user's runs with optional
``run_type`` / ``status`` filters and ``limit`` / ``offset`` pagination.

``GET /api/v1/agent-runs/{id}`` returns one run plus its step list so
the operator can replay the retrieve / generate / validate trace.

All queries are scoped by ``current_user.id`` so a run owned by another
user is invisible (returned as 404) so existence is never leaked.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.audit import AgentRun
from app.models.user import User
from app.schemas.audit import (
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentRunResponse,
)

router = APIRouter()


@router.get("", response_model=AgentRunListResponse)
def list_agent_runs(
    run_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunListResponse:
    """List the current user's agent runs with optional filters."""
    query = db.query(AgentRun).filter(AgentRun.user_id == current_user.id)
    if run_type is not None:
        query = query.filter(AgentRun.run_type == run_type)
    if status is not None:
        query = query.filter(AgentRun.status == status)

    total = query.count()
    rows = (
        query.order_by(AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    items = [AgentRunResponse.model_validate(r) for r in rows]
    return AgentRunListResponse(items=items, total=total)


@router.get("/{run_id}", response_model=AgentRunDetailResponse)
def get_agent_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunDetailResponse:
    """Return one agent run (with steps) — 404 if not owned by the user."""
    run = (
        db.query(AgentRun)
        .options(selectinload(AgentRun.steps))
        .filter(
            AgentRun.id == run_id,
            AgentRun.user_id == current_user.id,
        )
        .first()
    )
    if run is None:
        raise NotFoundException(message="Agent 运行记录不存在")
    return AgentRunDetailResponse.model_validate(run)
