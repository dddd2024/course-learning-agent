"""Task execution service for study-plan tasks.

PLAN-V3-02: Implements task start, verify, and auto-completion logic.

- ``start_task``: Creates a quiz for quiz-type tasks (or any task that
  doesn't yet have a bound quiz), binds the ``quiz_id`` to the task's
  ``target_id``, and records ``started_at``. Returns routing info so
  the frontend can navigate to the appropriate learning resource.

- ``verify_task``: Checks whether a task's completion criteria are met
  (e.g. quiz score >= threshold). On pass, auto-completes the task,
  the associated Todo, and recalculates the parent Goal's progress.

- ``get_execution_info``: Returns the current execution status,
  verification method, verification result, and timestamps for a task.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.quiz import generate_quiz
from app.core.exceptions import BusinessException, NotFoundException
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.plan import StudyGoal, StudyTask, Todo
from app.models.quiz import Quiz, QuizItem
from app.services.llm_config_service import build_user_config, get_active_config

logger = logging.getLogger(__name__)

_DEFAULT_PASS_SCORE = 60


def _get_owned_task(db: Session, task_id: int, user_id: int) -> StudyTask:
    """Return the task if it belongs to ``user_id``, else 404."""
    task = (
        db.query(StudyTask)
        .join(StudyGoal, StudyGoal.id == StudyTask.goal_id)
        .filter(
            StudyTask.id == task_id,
            StudyGoal.user_id == user_id,
        )
        .first()
    )
    if task is None:
        raise NotFoundException(message="任务不存在")
    return task


def _create_quiz_for_task(
    db: Session,
    task: StudyTask,
    user_id: int,
) -> int:
    """Create a quiz for the task's course and return the quiz_id.

    Replicates the logic from the ``POST /quizzes`` endpoint: resolves
    knowledge points, calls ``generate_quiz``, persists ``Quiz`` +
    ``QuizItem`` rows.
    """
    course = (
        db.query(Course)
        .filter(Course.id == task.course_id, Course.user_id == user_id)
        .first()
    )
    if course is None:
        raise NotFoundException(message="课程不存在")

    rows = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == task.course_id,
            KnowledgePoint.user_id == user_id,
        )
        .order_by(KnowledgePoint.id.asc())
        .all()
    )

    # When no knowledge points exist yet, create an empty quiz with
    # insufficient_evidence flag rather than raising. The frontend can
    # show a remediation tip.
    active_config = get_active_config(db, user_id)
    user_config = build_user_config(active_config) if active_config else None

    quiz_output = generate_quiz(
        db=db,
        user_id=user_id,
        course_id=task.course_id,
        knowledge_points=rows,
        course_name=course.name,
        question_count=5,
        user_config=user_config,
    )

    quiz = Quiz(
        user_id=user_id,
        course_id=task.course_id,
        title=quiz_output.get("title", f"{course.name} 测验"),
        question_count=len(quiz_output.get("items", [])),
        status="draft",
    )
    db.add(quiz)
    db.flush()

    for item_data in quiz_output.get("items", []):
        item = QuizItem(
            quiz_id=quiz.id,
            knowledge_point_id=item_data.get("knowledge_point_id"),
            question_type=item_data.get("question_type", "short_answer"),
            question_text=item_data.get("question_text", ""),
            options=json.dumps(item_data.get("options", []), ensure_ascii=False),
            answer=item_data.get("answer", ""),
            explanation=item_data.get("explanation", ""),
            difficulty=item_data.get("difficulty"),
            source_evidence_ids=json.dumps(item_data.get("source_evidence_ids", [])),
            evidence_snapshot=json.dumps(item_data.get("source_evidence_ids", [])),
            source_evidence=json.dumps(
                item_data.get("source_evidence", []), ensure_ascii=False
            ),
            verification_status=item_data.get("verification_status", "verified"),
            rubric_json=json.dumps(item_data.get("rubric", []), ensure_ascii=False),
            order_index=item_data.get("order_index", 0),
        )
        db.add(item)

    db.flush()
    return quiz.id


def _build_route_info(task: StudyTask, quiz_id: int | None) -> dict[str, Any]:
    """Build routing info for the frontend based on task type."""
    route = ""
    params: dict[str, Any] = {}

    if task.task_type == "quiz" or quiz_id is not None:
        route = f"/quizzes/{quiz_id}" if quiz_id else ""
        params = {"quiz_id": quiz_id}
    elif task.task_type == "learn":
        route = f"/courses/{task.course_id}/learn"
        params = {"course_id": task.course_id}
    elif task.task_type == "review":
        route = f"/courses/{task.course_id}/learn"
        params = {"course_id": task.course_id, "mode": "review"}

    return {"route": route, "params": params}


def start_task(db: Session, task_id: int, user_id: int) -> dict[str, Any]:
    """Start task execution.

    For quiz tasks (or any task without a bound quiz): creates a Quiz
    if ``target_id`` is empty, binds ``target_id`` to the new
    ``quiz_id``, and sets ``started_at``.

    Returns ``{"route": str, "params": dict, "target_id": int,
    "quiz_id": int, "target_type": str}``.
    """
    task = _get_owned_task(db, task_id, user_id)
    now = datetime.now()

    quiz_id: int | None = None

    # If the task already has a bound quiz, reuse it.
    if task.target_type == "quiz" and task.target_id is not None:
        quiz_id = task.target_id
    else:
        # Create a new quiz and bind it to the task.
        quiz_id = _create_quiz_for_task(db, task, user_id)
        task.target_type = "quiz"
        task.target_id = quiz_id

    if task.started_at is None:
        task.started_at = now
    task.last_action_at = now
    if task.execution_status == "pending":
        task.execution_status = "in_progress"

    db.commit()
    db.refresh(task)

    route_info = _build_route_info(task, quiz_id)
    return {
        "route": route_info["route"],
        "params": route_info["params"],
        "target_id": quiz_id,
        "quiz_id": quiz_id,
        "target_type": task.target_type,
        "execution_status": task.execution_status,
        "started_at": task.started_at.isoformat() if task.started_at else None,
    }


def _recalculate_goal_progress(db: Session, goal_id: int) -> None:
    """Recalculate the parent Goal's progress after a task completes.

    Updates the Goal's status to ``done`` if all tasks are done.
    """
    tasks = (
        db.query(StudyTask)
        .filter(StudyTask.goal_id == goal_id)
        .all()
    )
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status in {"done", "completed"})

    if total > 0 and completed == total:
        goal = db.query(StudyGoal).filter(StudyGoal.id == goal_id).first()
        if goal is not None and goal.status != "done":
            goal.status = "done"


def _complete_associated_todos(db: Session, task_id: int, user_id: int) -> int:
    """Mark all pending todos for a task as completed.

    Returns the number of todos completed.
    """
    todos = (
        db.query(Todo)
        .filter(
            Todo.task_id == task_id,
            Todo.user_id == user_id,
            Todo.status != "completed",
        )
        .all()
    )
    now = datetime.now()
    count = 0
    for todo in todos:
        todo.status = "completed"
        todo.completed_at = now
        count += 1
    return count


def verify_task(
    db: Session,
    task_id: int,
    user_id: int,
    score: int | None = None,
    threshold: int = _DEFAULT_PASS_SCORE,
) -> dict[str, Any]:
    """Verify task completion.

    For quiz tasks: checks if ``score >= threshold``. If pass,
    auto-completes the task + Todo + recalculates Goal progress.

    Returns ``{"verified": bool, "verification_result": dict,
    "completion_status": str}``.
    """
    task = _get_owned_task(db, task_id, user_id)
    now = datetime.now()

    # Determine verification method based on task type / target.
    if task.target_type == "quiz" or task.task_type == "quiz":
        verification_method = "quiz_score"
    elif task.task_type == "learn":
        verification_method = "reading_completion"
    elif task.task_type == "review":
        verification_method = "kp_viewed"
    else:
        verification_method = "manual"

    verified = False
    verification_result: dict[str, Any] = {
        "method": verification_method,
        "score": score,
        "threshold": threshold,
    }

    # Score-based verification: when a score is provided, use it as the
    # primary verification criterion regardless of task type. This allows
    # the verify endpoint to accept quiz scores, self-assessment scores,
    # or any numeric proof of completion.
    if score is not None:
        verified = score >= threshold
        verification_method = "score_threshold"
        verification_result["method"] = verification_method
        verification_result["passed"] = verified
        if not verified:
            verification_result["reason"] = f"分数 {score} 未达到阈值 {threshold}"
    elif task.target_type == "quiz" or task.task_type == "quiz":
        # Quiz task without a score — cannot auto-verify.
        verified = False
        verification_result["passed"] = False
        verification_result["reason"] = "未提供测验分数"
    elif task.task_type in ("learn", "review"):
        # Simplified: accept manual confirmation if started_at is set.
        verified = task.started_at is not None
        verification_result["passed"] = verified
        if not verified:
            verification_result["reason"] = "尚未开始学习" if task.task_type == "learn" else "尚未开始复习"
    else:
        # Default: cannot verify without evidence.
        verified = False
        verification_result["passed"] = False
        verification_result["reason"] = "无验证证据"

    if verified:
        task.status = "done"
        task.execution_status = "completed"
        task.completed_at = now
        task.auto_completed_at = now
        task.verification_method = verification_method
        task.verification_result_json = json.dumps(
            verification_result, ensure_ascii=False
        )
        task.last_action_at = now

        # Complete associated todos.
        todos_completed = _complete_associated_todos(db, task_id, user_id)
        verification_result["todos_completed"] = todos_completed

        # Recalculate parent goal progress.
        _recalculate_goal_progress(db, task.goal_id)

        db.commit()
        db.refresh(task)

        return {
            "verified": True,
            "verification_result": verification_result,
            "completion_status": "completed",
            "execution_status": task.execution_status,
            "status": task.status,
        }
    else:
        task.verification_method = verification_method
        task.verification_result_json = json.dumps(
            verification_result, ensure_ascii=False
        )
        task.last_action_at = now
        db.commit()
        db.refresh(task)

        return {
            "verified": False,
            "verification_result": verification_result,
            "completion_status": "failed_verification",
            "execution_status": task.execution_status,
            "status": task.status,
        }


def override_task(
    db: Session,
    task_id: int,
    user_id: int,
    reason: str,
) -> dict[str, Any]:
    """Manually override a task to completed with an audit trail.

    Records the user, time, reason, and sets
    ``verification_method=manual_override``.
    """
    task = _get_owned_task(db, task_id, user_id)
    now = datetime.now()

    override_record = {
        "user_id": user_id,
        "timestamp": now.isoformat(),
        "reason": reason,
        "previous_status": task.status,
        "previous_execution_status": task.execution_status,
    }

    task.status = "done"
    task.execution_status = "completed"
    task.completed_at = now
    task.auto_completed_at = now
    task.verification_method = "manual_override"
    task.verification_result_json = json.dumps(
        override_record, ensure_ascii=False
    )
    task.last_action_at = now

    # Complete associated todos.
    todos_completed = _complete_associated_todos(db, task_id, user_id)

    # Recalculate parent goal progress.
    _recalculate_goal_progress(db, task.goal_id)

    db.commit()
    db.refresh(task)

    return {
        "verified": True,
        "verification_result": override_record,
        "completion_status": "completed",
        "execution_status": task.execution_status,
        "status": task.status,
        "todos_completed": todos_completed,
    }


def get_execution_info(
    db: Session,
    task_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Return task execution status, verification info, and timestamps."""
    task = _get_owned_task(db, task_id, user_id)

    verification_result: dict[str, Any] | None = None
    if task.verification_result_json:
        try:
            parsed = json.loads(task.verification_result_json)
            verification_result = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            verification_result = None

    target_spec: dict[str, Any] | None = None
    if task.target_spec_json:
        try:
            parsed = json.loads(task.target_spec_json)
            target_spec = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            target_spec = None

    return {
        "task_id": task.id,
        "target_type": task.target_type,
        "target_id": task.target_id,
        "target_spec": target_spec,
        "execution_status": task.execution_status,
        "verification_method": task.verification_method,
        "verification_result": verification_result,
        "auto_completed_at": task.auto_completed_at.isoformat()
        if task.auto_completed_at
        else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat()
        if task.completed_at
        else None,
        "last_action_at": task.last_action_at.isoformat()
        if task.last_action_at
        else None,
    }
