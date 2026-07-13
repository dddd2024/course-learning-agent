"""Single authority for whether a multi-course plan can be physically deleted."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.plan import MultiCoursePlanTask, StudyTask, TaskExecutionEvent, Todo


def has_execution_history(db: Session, plan_id: int) -> bool:
    task_ids = [row[0] for row in db.query(MultiCoursePlanTask.task_id).filter(
        MultiCoursePlanTask.multi_plan_id == plan_id,
        MultiCoursePlanTask.task_id.isnot(None),
    ).all()]
    if not task_ids:
        return False
    if db.query(TaskExecutionEvent.id).filter(TaskExecutionEvent.task_id.in_(task_ids)).first():
        return True
    if db.query(Todo.id).filter(Todo.task_id.in_(task_ids), Todo.status == "completed").first():
        return True
    return bool(db.query(StudyTask.id).filter(
        StudyTask.id.in_(task_ids),
        (
            (StudyTask.execution_status != "pending")
            | StudyTask.started_at.isnot(None)
            | StudyTask.completed_at.isnot(None)
            | StudyTask.verification_result_json.isnot(None)
        ),
    ).first())
