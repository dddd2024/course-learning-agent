"""Single authority for whether a multi-course plan can be physically deleted."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.plan import MultiCoursePlan, MultiCoursePlanTask, StudyTask, TaskExecutionEvent, Todo
from app.models.quiz import Quiz


def has_execution_history(db: Session, plan_id: int) -> bool:
    plan = db.query(MultiCoursePlan).filter(MultiCoursePlan.id == plan_id).first()
    if plan is None:
        return False
    tasks = db.query(StudyTask).join(
        MultiCoursePlanTask, MultiCoursePlanTask.task_id == StudyTask.id,
    ).filter(MultiCoursePlanTask.multi_plan_id == plan_id).all()
    task_ids = [task.id for task in tasks]
    if not task_ids:
        return False
    if db.query(TaskExecutionEvent.id).filter(TaskExecutionEvent.task_id.in_(task_ids)).first():
        return True
    if db.query(Todo.id).filter(Todo.task_id.in_(task_ids), Todo.status == "completed").first():
        return True
    if db.query(StudyTask.id).filter(
        StudyTask.id.in_(task_ids),
        (
            (StudyTask.execution_status != "pending")
            | StudyTask.started_at.isnot(None)
            | StudyTask.completed_at.isnot(None)
            | StudyTask.verification_result_json.isnot(None)
        ),
    ).first():
        return True

    # A submitted quiz is durable execution evidence even when its linked
    # StudyTask remains pending and no Todo/event has been written yet. Only
    # inspect quiz ids named by tasks that belong to this plan; then scope the
    # quiz rows to the plan owner to prevent unrelated records from blocking a
    # pristine plan.
    quiz_ids: set[int] = set()
    for task in tasks:
        if task.task_type != "quiz":
            continue
        if task.target_type == "quiz" and task.target_id is not None:
            quiz_ids.add(task.target_id)
        try:
            target_spec = json.loads(task.target_spec_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            target_spec = {}
        if isinstance(target_spec, dict):
            history_ids = target_spec.get("history_quiz_ids", [])
            if isinstance(history_ids, list):
                quiz_ids.update(
                    int(quiz_id)
                    for quiz_id in history_ids
                    if str(quiz_id).isdigit()
                )
    return bool(quiz_ids) and bool(db.query(Quiz.id).filter(
        Quiz.id.in_(quiz_ids),
        Quiz.user_id == plan.user_id,
        Quiz.status == "submitted",
    ).first())
