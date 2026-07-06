"""Dashboard summary response schema."""
from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    """Aggregate counts for the dashboard landing page.

    All counts are scoped to the current user so cross-user data never
    leaks into the summary.
    """

    course_count: int
    material_count: int
    knowledge_point_count: int
    todo_today_count: int
    todo_completed_count: int
    agent_run_count: int
