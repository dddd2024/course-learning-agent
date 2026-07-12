"""Dashboard summary endpoint.

``GET /api/v1/dashboard/summary`` returns aggregate counts for the
current user so the frontend dashboard can render stat cards in a
single request instead of fanning out to six list endpoints.

All counts are scoped by ``current_user.id`` so cross-user data is
never leaked.
"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.audit import AgentRun
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.plan import Todo
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse

router = APIRouter()


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummaryResponse:
    """Return the current user's aggregate dashboard counts."""
    uid = current_user.id
    today = date.today()

    course_count = (
        db.query(Course).filter(Course.user_id == uid).count()
    )
    material_count = (
        db.query(Material).filter(Material.user_id == uid).count()
    )
    knowledge_point_count = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.user_id == uid, KnowledgePoint.status == "active")
        .count()
    )
    todo_today_count = (
        db.query(Todo)
        .filter(
            Todo.user_id == uid,
            Todo.scheduled_date == today,
            Todo.status != "completed",
        )
        .count()
    )
    todo_completed_count = (
        db.query(Todo)
        .filter(Todo.user_id == uid, Todo.status == "completed")
        .count()
    )
    agent_run_count = (
        db.query(AgentRun).filter(AgentRun.user_id == uid).count()
    )

    return DashboardSummaryResponse(
        course_count=course_count,
        material_count=material_count,
        knowledge_point_count=knowledge_point_count,
        todo_today_count=todo_today_count,
        todo_completed_count=todo_completed_count,
        agent_run_count=agent_run_count,
    )
