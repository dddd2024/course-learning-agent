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
from app.models.plan import StudyGoal, StudyTask, TaskExecutionEvent, Todo
from app.models.quiz import Quiz, QuizItem
from app.services.llm_config_service import build_user_config, get_active_config
from app.services.task_target_resolver import ensure_target_spec
from app.services.plan_state_service import recompute_goal, mark_task_completed

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
    spec = ensure_target_spec(db, task)
    course = (
        db.query(Course)
        .filter(Course.id == task.course_id, Course.user_id == user_id)
        .first()
    )
    if course is None:
        raise NotFoundException(message="课程不存在")

    target_ids = [int(value) for value in spec.get("knowledge_point_ids", []) if str(value).isdigit()]
    rows = (
        db.query(KnowledgePoint)
        .filter(
            KnowledgePoint.course_id == task.course_id,
            KnowledgePoint.user_id == user_id,
            KnowledgePoint.status == "active",
        )
        .filter(KnowledgePoint.id.in_(target_ids) if target_ids else True)
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
        question_count=max(1, int(spec.get("question_count", 5))),
        user_config=user_config,
    )

    items = quiz_output.get("items", [])
    if not items:
        raise BusinessException(message="资料证据不足，无法生成有效测验；请补充并解析课程资料后重试", status_code=422)
    quiz = Quiz(
        user_id=user_id,
        course_id=task.course_id,
        title=quiz_output.get("title", f"{course.name} 测验"),
        question_count=len(items),
        status="draft",
    )
    db.add(quiz)
    db.flush()

    for item_data in items:
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


def _record_event(db: Session, task: StudyTask, user_id: int, event_type: str, payload: dict | None = None) -> None:
    db.add(TaskExecutionEvent(
        task_id=task.id, user_id=user_id, event_type=event_type,
        target_type=task.target_type, target_id=task.target_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False), occurred_at=datetime.now(),
    ))


def _build_route_info(task: StudyTask, quiz_id: int | None) -> dict[str, Any]:
    """Build routing info for the frontend based on task type."""
    route = ""
    params: dict[str, Any] = {}

    if task.task_type == "quiz":
        route = "/quizzes"
        params = {"quiz_id": quiz_id}
    elif task.task_type == "learn":
        route = "/courses/:courseId/learn"
        params = {"course_id": task.course_id, "material_id": task.target_id}
    elif task.task_type == "review":
        route = "/courses/:courseId/outline"
        params = {"course_id": task.course_id, "knowledge_point_id": task.target_id, "task_id": task.id, "plan_id": task.goal_id}

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

    spec = ensure_target_spec(db, task)
    quiz_id: int | None = None
    if task.task_type == "quiz":
        if task.target_type != "quiz":
            raise BusinessException(message="测验任务目标类型无效", status_code=409)
        if task.target_id is None:
            quiz_id = _create_quiz_for_task(db, task, user_id)
            task.target_id = quiz_id
        else:
            quiz_id = task.target_id
    elif task.task_type == "learn":
        if task.target_type != "material" or task.target_id is None:
            raise BusinessException(message=spec.get("remediation", "学习任务缺少可用资料"), status_code=422)
    elif task.task_type == "review":
        if task.target_type != "knowledge_point" or task.target_id is None:
            raise BusinessException(message=spec.get("remediation", "复习任务缺少可用知识点"), status_code=422)
    else:
        raise BusinessException(message="不支持的任务类型", status_code=422)

    if task.started_at is None:
        task.started_at = now
    task.last_action_at = now
    if task.execution_status == "pending":
        task.execution_status = "in_progress"

    db.commit()
    db.refresh(task)

    route_info = _build_route_info(task, quiz_id)
    action_type = {"learn": "open_material", "review": "open_knowledge_point", "quiz": "open_quiz"}[task.task_type]
    route_name = {"learn": "course-learn", "review": "course-outline", "quiz": "quizzes"}[task.task_type]
    return {
        "route": route_info["route"],
        "params": route_info["params"],
        "action_type": action_type,
        "route_name": route_name,
        "route_params": route_info["params"],
        "target_id": task.target_id,
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


def record_task_event(db: Session, task_id: int, user_id: int, event_type: str, target_id: int, material_version_id: int | None = None, note: str | None = None) -> dict[str, Any]:
    task = _get_owned_task(db, task_id, user_id)
    allowed = {"learn": {"target_loaded", "user_confirmed"}, "review": {"target_loaded", "review_confirmed"}}
    if event_type not in allowed.get(task.task_type, set()):
        raise BusinessException(message="该任务不接受此执行事件", status_code=422)
    spec = ensure_target_spec(db, task)
    payload = {"note": note} if note else {}
    expected = spec.get("material_id") if task.task_type == "learn" else spec.get("knowledge_point_id")
    if expected is None:
        raise BusinessException(message="任务目标未解析", status_code=409)
    if target_id != expected:
        raise BusinessException(message="事件目标与任务目标不一致", status_code=409)
    expected_version = spec.get("material_version_id")
    if expected_version is not None and material_version_id != expected_version:
        raise BusinessException(message="资料版本与任务目标不一致", status_code=409)
    payload.update({"target_id": target_id, "material_version_id": material_version_id})
    _record_event(db, task, user_id, event_type, payload)
    task.last_action_at = datetime.now()
    db.commit()
    return {"recorded": True, "event_type": event_type}


def retry_task(db: Session, task_id: int, user_id: int) -> dict[str, Any]:
    task = _get_owned_task(db, task_id, user_id)
    if task.task_type != "quiz":
        raise BusinessException(message="只有测验任务可以重新练习", status_code=422)
    spec = ensure_target_spec(db, task)
    history = list(spec.get("history_quiz_ids") or [])
    if task.target_id is not None and task.target_id not in history:
        history.append(task.target_id)
    new_id = _create_quiz_for_task(db, task, user_id)
    spec["history_quiz_ids"] = history
    task.target_type, task.target_id = "quiz", new_id
    task.target_spec_json = json.dumps(spec, ensure_ascii=False)
    task.execution_status, task.status, task.completed_at = "in_progress", "pending", None
    task.last_action_at = datetime.now()
    recompute_goal(db, task.goal_id)
    db.commit()
    return {"quiz_id": new_id, "target_id": new_id, "history_quiz_ids": history, "action_type": "open_quiz", "route_name": "quizzes", "route_params": {"quiz_id": new_id}}


def verify_task(db: Session, task_id: int, user_id: int, confirmation: bool | None = None, note: str | None = None) -> dict[str, Any]:
    """Verify task completion.

    For quiz tasks: checks if ``score >= threshold``. If pass,
    auto-completes the task + Todo + recalculates Goal progress.

    Returns ``{"verified": bool, "verification_result": dict,
    "completion_status": str}``.
    """
    task = _get_owned_task(db, task_id, user_id)
    now = datetime.now()

    spec = ensure_target_spec(db, task)
    verification_method = "quiz_score" if task.task_type == "quiz" else f"{task.task_type}_events"
    verified = False
    verification_result: dict[str, Any] = {"method": verification_method, "verified_at": now.isoformat()}
    if task.task_type == "quiz":
        quiz = db.query(Quiz).filter(Quiz.id == task.target_id, Quiz.user_id == user_id, Quiz.course_id == task.course_id).first()
        threshold = int(spec.get("pass_score", _DEFAULT_PASS_SCORE))
        if quiz is None:
            verification_result.update({"passed": False, "reason": "未绑定用户自己的测验"})
        elif quiz.status != "submitted" or quiz.question_count <= 0:
            verification_result.update({"passed": False, "reason": "测验尚未有效提交", "quiz_id": quiz.id})
        else:
            percent = (quiz.score or 0) / quiz.question_count * 100
            verified = percent >= threshold
            verification_result.update({"quiz_id": quiz.id, "score": quiz.score or 0, "question_count": quiz.question_count, "score_percent": percent, "pass_score": threshold, "passed": verified})
    else:
        required = {"learn": {"target_loaded", "user_confirmed"}, "review": {"target_loaded", "review_confirmed"}}[task.task_type]
        if confirmation:
            _record_event(db, task, user_id, "user_confirmed" if task.task_type == "learn" else "review_confirmed", {"note": note} if note else {})
        seen = {row.event_type for row in db.query(TaskExecutionEvent).filter(TaskExecutionEvent.task_id == task.id, TaskExecutionEvent.user_id == user_id).all()}
        verified = required <= seen
        verification_result.update({"required_events": sorted(required), "observed_events": sorted(seen), "passed": verified})
        if not verified:
            verification_result["reason"] = "尚缺少学习或确认事件"

    if verified:
        todos_completed = mark_task_completed(db, task)
        task.verification_method = verification_method
        task.verification_result_json = json.dumps(
            verification_result, ensure_ascii=False
        )
        task.last_action_at = now

        verification_result["todos_completed"] = todos_completed

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

    todos_completed = mark_task_completed(db, task, manual=True)
    task.verification_method = "manual_override"
    task.verification_result_json = json.dumps(
        override_record, ensure_ascii=False
    )
    task.last_action_at = now

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
