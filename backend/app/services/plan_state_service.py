"""Single state-transition authority for StudyTask, Todo and StudyGoal."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session

from app.models.plan import StudyGoal, StudyTask, Todo


def recompute_goal(db: Session, goal_id: int) -> None:
    tasks = db.query(StudyTask).filter(StudyTask.goal_id == goal_id).all()
    goal = db.query(StudyGoal).filter(StudyGoal.id == goal_id).first()
    if goal is not None:
        goal.status = "done" if tasks and all(t.status in {"done", "completed"} for t in tasks) else "active"


def reopen_task(db: Session, task: StudyTask) -> None:
    task.status = "pending"
    task.execution_status = "pending"
    task.completed_at = None
    task.auto_completed_at = None
    for todo in db.query(Todo).filter(Todo.task_id == task.id).all():
        todo.status = "pending"
        todo.completed_at = None
    recompute_goal(db, task.goal_id)


def todo_update_allowed(todo: Todo, status: str | None) -> None:
    if status == "completed" and todo.task_id:
        raise ValueError("关联学习任务必须从任务验证入口完成，待办不能绕过服务端验收")


def mark_task_completed(db: Session, task: StudyTask) -> None:
    now = datetime.now()
    task.status = "done"
    task.execution_status = "completed"
    task.completed_at = now
    task.auto_completed_at = now
    for todo in db.query(Todo).filter(Todo.task_id == task.id).all():
        todo.status = "completed"
        todo.completed_at = now
    recompute_goal(db, task.goal_id)
