"""Study-plan and todo endpoints.

``POST /api/v1/plans`` runs the ``PlannerAgent`` to decompose a goal,
persists ``StudyGoal`` / ``StudyTask`` rows, then calls the
``scheduler`` to expand tasks into per-day ``Todo`` rows.

``GET /api/v1/plans`` lists the current user's persisted goals with
task/todo progress. ``GET /api/v1/plans/{id}`` restores a complete plan.

``GET /api/v1/todos`` lists the current user's todos with optional
``date`` / ``status`` / ``course_id`` filters.

``PATCH /api/v1/todos/{id}`` updates a todo's status
(``completed`` / ``postponed``) or ``actual_minutes``.

All queries are scoped by ``current_user.id`` so a todo owned by
another user is invisible (returned as 404) so existence is never
leaked.
"""
import json
import logging
import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.planner import generate as planner_generate
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.plan import MultiCoursePlan, MultiCoursePlanTask, StudyGoal, StudyTask, Todo
from app.models.quiz import WeakPoint
from app.models.user import User
from app.services.weak_point_progress import apply_mastery_decay
from app.schemas.multi_plan import (
    MultiPlanCreate,
    MultiPlanResponse,
    MultiScheduleItem,
)
from app.schemas.plan import (
    GoalResponse,
    GoalUpdate,
    PlanCreate,
    PlanListResponse,
    PlanProgressResponse,
    PlanResponse,
    PlanSummaryResponse,
    TaskOverrideRequest,
    TaskEventRequest,
    TaskResponse,
    TaskUpdate,
    TaskVerifyRequest,
    TodoListResponse,
    TodoResponse,
    TodoUpdate,
)
from app.services.llm_config_service import (
    build_user_config,
    get_active_config,
)
from app.services.multi_scheduler import schedule_multi_courses
from app.services.scheduler import schedule_tasks_with_conflicts
from app.services.task_execution_service import (
    get_execution_info,
    override_task as override_task_service,
    start_task as start_task_service,
    retry_task as retry_task_service,
    record_task_event as record_task_event_service,
    verify_task as verify_task_service,
)
from app.services.task_target_resolver import resolve_target
from app.services.plan_state_service import todo_update_allowed

logger = logging.getLogger(__name__)
router = APIRouter()
todos_router = APIRouter()


def _normalise_task_type(value: str | None) -> str:
    value = (value or "review").strip().lower()
    return "quiz" if value in {"practice", "exercise", "test"} else value if value in {"learn", "review", "quiz"} else "review"


def _load_course_names(
    db: Session,
    course_ids: set[int],
    user_id: int | None = None,
) -> dict[int, str]:
    """Return ``{course_id: course_name}`` for the given course ids."""
    if not course_ids:
        return {}
    query = db.query(Course).filter(Course.id.in_(course_ids))
    if user_id is not None:
        query = query.filter(Course.user_id == user_id)
    rows = query.all()
    return {r.id: r.name for r in rows}


def _resolve_user_courses(
    db: Session,
    user_id: int,
    payload: PlanCreate,
) -> list[Course]:
    """Resolve owned courses, preferring stable ids over legacy names."""
    if payload.course_ids:
        requested_ids = list(dict.fromkeys(payload.course_ids))
        rows = (
            db.query(Course)
            .filter(
                Course.user_id == user_id,
                Course.id.in_(requested_ids),
            )
            .all()
        )
        by_id = {course.id: course for course in rows}
        if any(course_id not in by_id for course_id in requested_ids):
            raise NotFoundException(message="部分课程不存在或无权访问")
        return [by_id[course_id] for course_id in requested_ids]

    # Backward-compatible name lookup.  Duplicate names cannot be expressed
    # unambiguously by the legacy contract, so choose the oldest matching row
    # deterministically; new clients submit ``course_ids`` instead.
    requested_names = list(dict.fromkeys(payload.courses))
    rows = (
        db.query(Course)
        .filter(
            Course.user_id == user_id,
            Course.name.in_(requested_names),
        )
        .order_by(Course.id.asc())
        .all()
    )
    by_name: dict[str, Course] = {}
    for course in rows:
        by_name.setdefault(course.name, course)
    if any(name not in by_name for name in requested_names):
        raise NotFoundException(message="部分课程不存在或无权访问")
    return [by_name[name] for name in requested_names]


def _build_course_map(courses: list[Course]) -> dict[str, int]:
    """Build unambiguous planner labels mapped to stable course ids."""
    name_counts: dict[str, int] = {}
    for course in courses:
        name_counts[course.name] = name_counts.get(course.name, 0) + 1
    return {
        (
            f"{course.name}（课程 #{course.id}）"
            if name_counts[course.name] > 1
            else course.name
        ): course.id
        for course in courses
    }


def _build_weak_point_review_tasks(
    db: Session,
    user_id: int,
    course_map: dict[str, int],
) -> list[dict]:
    """Build review tasks for the user's weak points in the given courses.

    Each weak point becomes a ``review`` task titled ``复习薄弱点：{kp}``
    with boosted priority so the scheduler treats it as urgent. Returns
    a list of task dicts in the same shape as ``PlannerAgent`` output so
    they can be appended directly.
    """
    if not course_map:
        return []
    course_ids = list(course_map.values())
    rows = (
        db.query(WeakPoint, KnowledgePoint)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == WeakPoint.knowledge_point_id,
        )
        .filter(
            WeakPoint.user_id == user_id,
            WeakPoint.course_id.in_(course_ids),
        )
        .order_by(WeakPoint.id.asc())
        .all()
    )
    if any(apply_mastery_decay(wp) for wp, _ in rows):
        db.commit()
    id_to_name = {cid: name for name, cid in course_map.items()}
    tasks: list[dict] = []
    for wp, kp in sorted(
        rows,
        key=lambda row: (
            row[0].status == "resolved",
            row[0].mastery_score,
            -(row[0].wrong_count or 0),
            row[0].last_wrong_at or datetime.min,
        ),
    ):
        if wp.status == "resolved":
            continue
        tasks.append(
            {
                "course_name": id_to_name.get(wp.course_id, ""),
                "title": f"复习薄弱点：{kp.title}",
                "task_type": "review",
                "estimate_minutes": 30,
                "priority": 5,  # boosted so the scheduler prioritises it
                "acceptance": f"重做错题并确保掌握 {kp.title}",
            }
        )
    return tasks


def _task_to_response(task: StudyTask, course_name: str) -> TaskResponse:
    """Build a TaskResponse from a StudyTask ORM row.

    PLAN-V3-01: includes execution fields (target_type, target_id,
    target_spec, execution_status, verification_method,
    verification_result, started_at, completed_at, last_action_at).
    """
    return TaskResponse(
        id=task.id,
        goal_id=task.goal_id,
        course_id=task.course_id,
        course_name=course_name,
        title=task.title,
        task_type=task.task_type,
        estimate_minutes=task.estimate_minutes,
        priority=task.priority,
        acceptance=task.acceptance,
        status=task.status,
        target_type=task.target_type,
        target_id=task.target_id,
        target_spec=task.target_spec_json,
        execution_status=task.execution_status,
        verification_method=task.verification_method,
        verification_result=task.verification_result_json,
        auto_completed_at=task.auto_completed_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        last_action_at=task.last_action_at,
    )


def _todo_to_response(todo: Todo, course_name: str) -> TodoResponse:
    return TodoResponse(
        id=todo.id,
        user_id=todo.user_id,
        task_id=todo.task_id,
        course_id=todo.course_id,
        course_name=course_name,
        title=todo.title,
        scheduled_date=todo.scheduled_date,
        scheduled_start=todo.scheduled_start,
        scheduled_end=todo.scheduled_end,
        estimate_minutes=todo.estimate_minutes,
        status=todo.status,
        actual_minutes=todo.actual_minutes,
        completed_at=todo.completed_at,
    )


def _load_plan_response(
    db: Session,
    goal: StudyGoal,
    user_id: int,
) -> PlanResponse:
    """Restore a persisted goal with its tasks and scheduled todos."""
    tasks = (
        db.query(StudyTask)
        .filter(StudyTask.goal_id == goal.id)
        .order_by(StudyTask.id.asc())
        .all()
    )
    task_ids = [task.id for task in tasks]
    todos = []
    if task_ids:
        todos = (
            db.query(Todo)
            .filter(
                Todo.user_id == user_id,
                Todo.task_id.in_(task_ids),
            )
            .order_by(Todo.scheduled_date.asc(), Todo.id.asc())
            .all()
        )
    course_name_by_id = _load_course_names(
        db,
        {task.course_id for task in tasks}
        | {todo.course_id for todo in todos},
        user_id=user_id,
    )
    return PlanResponse(
        goal=GoalResponse.model_validate(goal),
        tasks=[
            _task_to_response(task, course_name_by_id.get(task.course_id, ""))
            for task in tasks
        ],
        todos=[
            _todo_to_response(todo, course_name_by_id.get(todo.course_id, ""))
            for todo in todos
        ],
    )


@router.get("", response_model=PlanListResponse)
def list_plans(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanListResponse:
    """List the current user's persisted learning goals and progress."""
    goals = (
        db.query(StudyGoal)
        .filter(StudyGoal.user_id == current_user.id)
        .order_by(StudyGoal.created_at.desc(), StudyGoal.id.desc())
        .all()
    )
    goal_ids = [goal.id for goal in goals]
    tasks = []
    if goal_ids:
        tasks = (
            db.query(StudyTask)
            .filter(StudyTask.goal_id.in_(goal_ids))
            .order_by(StudyTask.id.asc())
            .all()
        )
    task_ids = [task.id for task in tasks]
    todos = []
    if task_ids:
        todos = (
            db.query(Todo)
            .filter(
                Todo.user_id == current_user.id,
                Todo.task_id.in_(task_ids),
            )
            .order_by(Todo.id.asc())
            .all()
        )

    tasks_by_goal: dict[int, list[StudyTask]] = {goal_id: [] for goal_id in goal_ids}
    goal_id_by_task_id: dict[int, int] = {}
    for task in tasks:
        tasks_by_goal.setdefault(task.goal_id, []).append(task)
        goal_id_by_task_id[task.id] = task.goal_id
    todos_by_goal: dict[int, list[Todo]] = {goal_id: [] for goal_id in goal_ids}
    for todo in todos:
        goal_id = goal_id_by_task_id.get(todo.task_id)
        if goal_id is not None:
            todos_by_goal.setdefault(goal_id, []).append(todo)

    course_name_by_id = _load_course_names(
        db,
        {task.course_id for task in tasks},
        user_id=current_user.id,
    )
    items: list[PlanSummaryResponse] = []
    for goal in goals:
        goal_tasks = tasks_by_goal.get(goal.id, [])
        goal_todos = todos_by_goal.get(goal.id, [])
        course_ids = list(dict.fromkeys(task.course_id for task in goal_tasks))
        items.append(
            PlanSummaryResponse(
                goal=GoalResponse.model_validate(goal),
                course_ids=course_ids,
                course_names=[
                    course_name_by_id.get(course_id, "")
                    for course_id in course_ids
                ],
                progress=PlanProgressResponse(
                    tasks_total=len(goal_tasks),
                    tasks_completed=sum(
                        task.status in {"done", "completed"}
                        for task in goal_tasks
                    ),
                    todos_total=len(goal_todos),
                    todos_completed=sum(
                        todo.status == "completed" for todo in goal_todos
                    ),
                ),
                created_at=goal.created_at,
                updated_at=goal.updated_at,
            )
        )
    return PlanListResponse(items=items, total=len(items))


@router.get("/{goal_id}", response_model=PlanResponse)
def get_plan(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanResponse:
    """Restore one complete plan owned by the current user."""
    goal = (
        db.query(StudyGoal)
        .filter(
            StudyGoal.id == goal_id,
            StudyGoal.user_id == current_user.id,
        )
        .first()
    )
    if goal is None:
        raise NotFoundException(message="学习计划不存在")
    return _load_plan_response(db, goal, current_user.id)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    """Update a study task's status (404 if not owned).

    PLAN-V3-02: ``status=done`` / ``status=completed`` are rejected
    here — tasks can only be completed through the verify endpoint
    (or the manual override endpoint).
    """
    task = (
        db.query(StudyTask)
        .join(StudyGoal, StudyGoal.id == StudyTask.goal_id)
        .filter(
            StudyTask.id == task_id,
            StudyGoal.user_id == current_user.id,
        )
        .first()
    )
    if task is None:
        raise NotFoundException(message="任务不存在")

    if payload.status is not None and payload.status in {"done", "completed"}:
        raise BusinessException(
            message="任务不能直接标记为完成，请通过验证端点完成",
            status_code=400,
        )

    if payload.status is not None:
        task.status = payload.status

    db.commit()
    db.refresh(task)

    course = db.query(Course).filter(Course.id == task.course_id).first()
    course_name = course.name if course else ""
    return _task_to_response(task, course_name)


@router.post("/tasks/{task_id}/start")
def start_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Start task execution (PLAN-V3-02).

    For quiz tasks: creates a Quiz if ``target_id`` is empty and binds
    the resulting ``quiz_id`` to the task's ``target_id``. Sets
    ``started_at`` and returns routing info so the frontend can navigate
    to the created resource.
    """
    return start_task_service(db, task_id, current_user.id)


@router.post("/tasks/{task_id}/verify")
def verify_task(
    task_id: int,
    payload: TaskVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Verify from server-side quiz or task-event evidence only."""
    return verify_task_service(
        db,
        task_id,
        current_user.id,
        confirmation=payload.confirmation,
        note=payload.note,
    )


@router.post("/tasks/{task_id}/events")
def record_task_event(
    task_id: int,
    payload: TaskEventRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return record_task_event_service(db, task_id, current_user.id, payload.event_type, payload.target_id, payload.material_version_id, payload.note)


@router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return retry_task_service(db, task_id, current_user.id)


@router.get("/tasks/{task_id}/execution")
def get_task_execution(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get task execution info (PLAN-V3-02).

    Returns execution status, verification method, verification result,
    started_at, completed_at, etc.
    """
    return get_execution_info(db, task_id, current_user.id)


@router.post("/tasks/{task_id}/override")
def override_task(
    task_id: int,
    payload: TaskOverrideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually override a task to completed (PLAN-V3-02).

    Records user, time, reason, and sets
    ``verification_method=manual_override`` for audit trail.
    """
    return override_task_service(db, task_id, current_user.id, payload.reason)


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: int,
    payload: GoalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalResponse:
    """Update a study goal's status (404 if not owned)."""
    goal = (
        db.query(StudyGoal)
        .filter(
            StudyGoal.id == goal_id,
            StudyGoal.user_id == current_user.id,
        )
        .first()
    )
    if goal is None:
        raise NotFoundException(message="学习计划不存在")

    if payload.status is not None:
        goal.status = payload.status

    db.commit()
    db.refresh(goal)
    return GoalResponse.model_validate(goal)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a study goal and all its tasks and todos."""
    goal = (
        db.query(StudyGoal)
        .filter(
            StudyGoal.id == goal_id,
            StudyGoal.user_id == current_user.id,
        )
        .first()
    )
    if goal is None:
        raise NotFoundException(message="学习计划不存在")

    # Delete associated todos and tasks first
    task_ids = [t.id for t in db.query(StudyTask).filter(StudyTask.goal_id == goal_id).all()]
    if task_ids:
        db.query(Todo).filter(Todo.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(StudyTask).filter(StudyTask.goal_id == goal_id).delete(synchronize_session=False)
    db.query(StudyGoal).filter(StudyGoal.id == goal_id).delete(synchronize_session=False)
    db.commit()


@router.post("", response_model=PlanResponse)
def create_plan(
    payload: PlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanResponse:
    """Create a study plan: goal + tasks + per-day todos."""
    # 1. Validate every requested course belongs to the user.
    user_courses = _resolve_user_courses(db, current_user.id, payload)
    course_map = _build_course_map(user_courses)

    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None

    run_started_at = time.monotonic()

    # 2. Run the PlannerAgent to decompose the goal into tasks.
    #    The agent now manages its own audit run internally.
    try:
        plan_output = planner_generate(
            db=db,
            user_id=current_user.id,
            goal=payload.goal,
            courses=list(course_map),
            deadline=payload.deadline,
            daily_minutes=payload.daily_minutes,
            user_config=user_config,
        )
    except Exception as exc:
        raise

    # 2b. Append weak-point review tasks for any course in the plan that
    #     has recorded weak points. These get boosted priority so the
    #     scheduler front-loads them.
    weak_point_tasks = _build_weak_point_review_tasks(
        db, current_user.id, course_map
    )
    if weak_point_tasks:
        plan_output.setdefault("tasks", []).extend(weak_point_tasks)

    # 3. Persist the StudyGoal.
    goal = StudyGoal(
        user_id=current_user.id,
        title=plan_output.get("goal_title") or payload.goal,
        deadline=payload.deadline,
        daily_minutes=payload.daily_minutes,
        status="active",
    )
    db.add(goal)
    db.flush()

    # 4. Persist StudyTask rows (preserve LLM order so scheduler indices
    #    line up with the persisted list).
    task_rows: list[StudyTask] = []
    used_target_ids: dict[tuple[int, str], set[int]] = {}
    for task_data in plan_output.get("tasks", []):
        course_name = task_data.get("course_name", "")
        course_id = course_map.get(course_name)
        if course_id is None:
            # Defensive: skip any task whose course couldn't be resolved
            # rather than failing the whole plan creation.
            continue
        task_type = _normalise_task_type(task_data.get("task_type"))
        key = (course_id, task_type)
        target_type, target_id, target_spec = resolve_target(
            db, course_id, task_type, task_data.get("title", ""), used_target_ids.setdefault(key, set())
        )
        if target_id is not None:
            used_target_ids[key].add(target_id)
        task = StudyTask(
            goal_id=goal.id,
            course_id=course_id,
            title=task_data.get("title", ""),
            task_type=task_type,
            estimate_minutes=int(task_data.get("estimate_minutes", 60) or 60),
            priority=int(task_data.get("priority", 3) or 3),
            acceptance=task_data.get("acceptance", ""),
            status="pending",
            target_type=target_type,
            target_id=target_id,
            target_spec_json=json.dumps(target_spec, ensure_ascii=False),
            execution_status="pending",
        )
        db.add(task)
        db.flush()
        task_rows.append(task)

    # 5. Run the scheduler from today to the deadline.
    schedule_started = time.monotonic()
    today = date.today()
    task_dicts = [
        {
            "title": t.title,
            "course_name": next(
                (name for name, cid in course_map.items() if cid == t.course_id),
                "",
            ),
            "estimate_minutes": t.estimate_minutes,
            "priority": t.priority,
        }
        for t in task_rows
    ]
    scheduled, unscheduled = schedule_tasks_with_conflicts(
        tasks=task_dicts,
        start_date=today,
        deadline=payload.deadline,
        daily_minutes=payload.daily_minutes,
    )
    schedule_duration = int((time.monotonic() - schedule_started) * 1000)

    # 6. Persist Todo rows.
    todo_rows: list[Todo] = []
    for item in scheduled:
        idx = item["task_index"]
        if idx >= len(task_rows):
            continue
        task_obj = task_rows[idx]
        todo = Todo(
            user_id=current_user.id,
            task_id=task_obj.id,
            course_id=task_obj.course_id,
            title=item["title"] or task_obj.title,
            scheduled_date=item["scheduled_date"],
            estimate_minutes=item["estimate_minutes"],
            status="pending",
        )
        db.add(todo)
        db.flush()
        todo_rows.append(todo)

    db.commit()

    # 7. Build the response with denormalised course_name.
    course_name_by_id = {c.id: c.name for c in user_courses}
    tasks_resp = [
        _task_to_response(t, course_name_by_id.get(t.course_id, ""))
        for t in task_rows
    ]
    todos_resp = [
        _todo_to_response(t, course_name_by_id.get(t.course_id, ""))
        for t in todo_rows
    ]
    return PlanResponse(
        goal=GoalResponse.model_validate(goal),
        tasks=tasks_resp,
        todos=todos_resp,
        unscheduled_tasks=unscheduled,
    )


@router.post("/multi", response_model=MultiPlanResponse)
def create_multi_plan(
    payload: MultiPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MultiPlanResponse:
    """Create a coordinated study plan across multiple courses.

    1. Validate every ``course_id`` belongs to the current user (a missing
       or foreign course surfaces as 404 so existence is never leaked).
    2. Run ``schedule_multi_courses`` to decompose each course and pack
       tasks day-by-day honouring ``daily_minutes`` and the per-course
       90-minute continuous-learning cap.
    3. Persist one ``StudyGoal`` per course, one ``StudyTask`` per
       schedule item, and one ``Todo`` per schedule item.
    4. Return the schedule as ``MultiPlanResponse``.
    """
    requested_ids = [c.course_id for c in payload.courses]
    user_courses = (
        db.query(Course)
        .filter(
            Course.user_id == current_user.id,
            Course.id.in_(requested_ids),
        )
        .all()
    )
    found_ids = {c.id for c in user_courses}
    missing = [cid for cid in requested_ids if cid not in found_ids]
    if missing:
        raise NotFoundException(message="部分课程不存在或无权访问")

    # Build the input list for the scheduler with course_id + deadline
    # (and optional user_priority) for each requested course.
    # T0-1: 旧字段 priority（1-5）的归一化已在 schema 层的
    # ``_normalize_priority_input`` 完成，这里直接透传。
    courses_input = [
        {
            "course_id": c.course_id,
            "deadline": c.deadline,
            "user_priority": c.user_priority,
        }
        for c in payload.courses
    ]

    # T02: 读取当前用户启用的 LLM 配置并透传给 scheduler，确保多课程
    # 规划与聊天、知识点、单课程计划的模型配置行为一致。
    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None

    schedule = schedule_multi_courses(
        db=db,
        user_id=current_user.id,
        courses=courses_input,
        daily_minutes=payload.daily_minutes,
        user_config=user_config,
    )
    # Infeasible tasks are returned separately and must not become todos.
    schedule_items_raw = schedule["schedule"]
    overflow_warnings = schedule.get("overflow_warnings", [])
    unscheduled_tasks = schedule.get("unscheduled_tasks", [])

    parent = MultiCoursePlan(
        user_id=current_user.id,
        title="多课程学习计划",
        deadline=max(item.deadline for item in payload.courses),
        daily_minutes=payload.daily_minutes,
        status="active",
    )
    db.add(parent)
    db.flush()

    # Persist: one StudyGoal per course so each course's plan can be
    # managed independently, then one StudyTask + one Todo per schedule
    # item.
    course_name_by_id = {c.id: c.name for c in user_courses}
    goal_by_course: dict[int, StudyGoal] = {}
    items: list[MultiScheduleItem] = []

    used_target_ids: dict[tuple[int, str], set[int]] = {}
    for item in schedule_items_raw:
        course_id = item["course_id"]
        course_name = item.get("course_name") or course_name_by_id.get(course_id, "")

        if course_id not in goal_by_course:
            goal = StudyGoal(
                user_id=current_user.id,
                title=f"多课程学习计划 - {course_name}",
                deadline=item["scheduled_date"],  # placeholder; per-course deadline
                daily_minutes=payload.daily_minutes,
                status="active",
            )
            # Patch the deadline to the user-requested one for this course.
            requested = next(
                (c for c in payload.courses if c.course_id == course_id), None
            )
            if requested is not None:
                goal.deadline = requested.deadline
            db.add(goal)
            db.flush()
            goal_by_course[course_id] = goal

        task_type = _normalise_task_type(item.get("task_type"))
        key = (course_id, task_type)
        target_type, target_id, target_spec = resolve_target(
            db, course_id, task_type, item["title"], used_target_ids.setdefault(key, set())
        )
        if target_id is not None:
            used_target_ids[key].add(target_id)
        task = StudyTask(
            goal_id=goal_by_course[course_id].id,
            course_id=course_id,
            title=item["title"],
            task_type=task_type,
            estimate_minutes=item["estimate_minutes"],
            priority=int(item.get("priority", 3) or 3),
            acceptance=item.get("acceptance", ""),
            status="pending",
            target_type=target_type,
            target_id=target_id,
            target_spec_json=json.dumps(target_spec, ensure_ascii=False),
            execution_status="pending",
        )
        db.add(task)
        db.flush()

        db.add(MultiCoursePlanTask(
            multi_plan_id=parent.id,
            task_id=task.id,
            course_id=course_id,
            depends_on_json=json.dumps(item.get("depends_on", []), ensure_ascii=False),
            scheduled_date=item["scheduled_date"],
            estimate_minutes=item["estimate_minutes"],
        ))

        todo = Todo(
            user_id=current_user.id,
            task_id=task.id,
            course_id=course_id,
            title=item["title"],
            scheduled_date=item["scheduled_date"],
            scheduled_start=item.get("start_time"),
            scheduled_end=item.get("end_time"),
            estimate_minutes=item["estimate_minutes"],
            status="pending",
        )
        db.add(todo)
        db.flush()

        items.append(
            MultiScheduleItem(
                scheduled_date=item["scheduled_date"],
                course_name=course_name,
                title=item["title"],
                estimate_minutes=item["estimate_minutes"],
                start_time=item.get("start_time"),
                end_time=item.get("end_time"),
            )
        )

    for item in unscheduled_tasks:
        db.add(MultiCoursePlanTask(
            multi_plan_id=parent.id,
            task_id=None,
            course_id=item["course_id"],
            depends_on_json=json.dumps(item.get("depends_on", []), ensure_ascii=False),
            scheduled_date=None,
            estimate_minutes=item["estimate_minutes"],
            unscheduled_reason=item["reason"],
        ))
    db.commit()

    return MultiPlanResponse(
        schedule=items,
        overflow_warnings=overflow_warnings,
        unscheduled_tasks=unscheduled_tasks,
    )


@todos_router.get("", response_model=TodoListResponse)
def list_todos(
    date: date | None = Query(None),
    status: str | None = Query(None),
    course_id: int | None = Query(None),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TodoListResponse:
    """List owned todos, applying pagination when either page field is sent."""
    query = db.query(Todo).filter(Todo.user_id == current_user.id)
    if date is not None:
        query = query.filter(Todo.scheduled_date == date)
    if status is not None:
        query = query.filter(Todo.status == status)
    if course_id is not None:
        query = query.filter(Todo.course_id == course_id)

    total = query.count()
    ordered_query = query.order_by(Todo.scheduled_date.asc(), Todo.id.asc())
    if page is not None or page_size is not None:
        effective_page = page or 1
        effective_page_size = page_size or 20
        ordered_query = ordered_query.offset(
            (effective_page - 1) * effective_page_size
        ).limit(effective_page_size)
    rows = ordered_query.all()
    course_name_by_id = _load_course_names(
        db,
        {r.course_id for r in rows},
        user_id=current_user.id,
    )
    items = [
        _todo_to_response(r, course_name_by_id.get(r.course_id, ""))
        for r in rows
    ]
    return TodoListResponse(items=items, total=total)


@todos_router.patch("/{todo_id}", response_model=TodoResponse)
def update_todo(
    todo_id: int,
    payload: TodoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TodoResponse:
    """Update a todo's status / actual_minutes (404 if not owned)."""
    todo = (
        db.query(Todo)
        .filter(Todo.id == todo_id, Todo.user_id == current_user.id)
        .first()
    )
    if todo is None:
        raise NotFoundException(message="待办不存在")

    update_data = payload.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] is not None:
        try:
            todo_update_allowed(todo, update_data["status"])
        except ValueError as exc:
            raise BusinessException(message=str(exc), status_code=409)
        todo.status = update_data["status"]
        if update_data["status"] == "completed":
            todo.completed_at = datetime.now()
        else:
            todo.completed_at = None
    if "actual_minutes" in update_data and update_data["actual_minutes"] is not None:
        todo.actual_minutes = update_data["actual_minutes"]

    db.commit()
    db.refresh(todo)

    course = db.query(Course).filter(Course.id == todo.course_id).first()
    course_name = course.name if course else ""
    return _todo_to_response(todo, course_name)

