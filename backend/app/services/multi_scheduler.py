"""Multi-course scheduler — coordinates study plans across several courses.

Given a list of courses (each with its own ``deadline`` and optional
``user_priority``), the scheduler:

1. Decomposes each course into stage tasks via :func:`PlannerAgent.generate`.
2. Computes a ``priority_score`` per course using the formula
   ``deadline_urgency*0.45 + workload_weight*0.30
   + weak_point_weight*0.15 + user_priority*0.10``.
3. Sorts courses by ``priority_score`` descending (high-priority first).
4. Walks days from today to the latest deadline, packing each task into
   the earliest day that satisfies BOTH:
   - per-day total <= ``daily_minutes``
   - per-course-per-day total <= 90 minutes (the "continuous learning"
     cap; tasks that would exceed it roll forward to the next day).

The return value is a flat list of schedule items (one per task, sorted
by ``scheduled_date``) ready for ``StudyGoal`` / ``StudyTask`` / ``Todo``
persistence by the API layer.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents.planner import generate as planner_generate
from app.models.course import Course

# Per-course-per-day continuous-learning cap (section 11.6 of the design
# doc: 同一课程连续学习不超 90 分钟).
_PER_COURSE_DAILY_CAP_MIN = 90


def compute_priority_score(
    deadline_urgency: float,
    workload_weight: float,
    weak_point_weight: float,
    user_priority: float,
) -> float:
    """Return the weighted priority score for a course.

    priority_score = deadline_urgency*0.45 + workload_weight*0.30
                     + weak_point_weight*0.15 + user_priority*0.10
    """
    return (
        deadline_urgency * 0.45
        + workload_weight * 0.30
        + weak_point_weight * 0.15
        + user_priority * 0.10
    )


def schedule_multi_courses(
    db: Session,
    user_id: int,
    courses: list[dict[str, Any]],
    daily_minutes: int,
) -> list[dict[str, Any]]:
    """Schedule tasks across multiple courses honouring daily + 90-min caps.

    Args:
        db: SQLAlchemy session (passed through to ``PlannerAgent``).
        user_id: The user the plan is being built for.
        courses: Each dict carries ``course_id``, ``deadline`` (a
            ``date``), and an optional ``user_priority`` in ``[0, 1]``
            (defaults to ``0.5`` when omitted).
        daily_minutes: Per-day budget shared across all courses.

    Returns:
        A list of schedule dicts sorted by ``scheduled_date``. Each
        dict carries ``scheduled_date``, ``course_id``, ``course_name``,
        ``title``, ``task_type``, ``estimate_minutes``, ``priority``,
        ``acceptance``, ``start_time`` (None) and ``end_time`` (None) —
        enough for the API layer to persist ``StudyTask`` and ``Todo``
        rows without a second lookup.
    """
    if not courses:
        return []

    # 1. Look up course names for the requested course_ids.
    course_ids = [int(c["course_id"]) for c in courses]
    rows = db.query(Course).filter(Course.id.in_(course_ids)).all()
    course_name_by_id = {r.id: r.name for r in rows}

    today = date.today()

    # 2. Decompose each course via PlannerAgent and gather metadata for
    #    the priority-score computation.
    course_plans: list[dict[str, Any]] = []
    total_workload = 0
    for c in courses:
        course_id = int(c["course_id"])
        deadline: date = c["deadline"]
        user_priority = float(c.get("user_priority") or 0.5)
        course_name = course_name_by_id.get(course_id, "")

        plan_output = planner_generate(
            db=db,
            user_id=user_id,
            goal=f"完成 {course_name} 学习计划",
            courses=[course_name],
            deadline=deadline,
            daily_minutes=daily_minutes,
        )
        tasks = plan_output.get("tasks", []) or []
        workload = sum(int(t.get("estimate_minutes", 0) or 0) for t in tasks)

        remaining_days = max(1, (deadline - today).days)
        deadline_urgency = 1.0 / remaining_days

        course_plans.append(
            {
                "course_id": course_id,
                "course_name": course_name,
                "deadline": deadline,
                "tasks": tasks,
                "workload": workload,
                "deadline_urgency": deadline_urgency,
                "user_priority": user_priority,
            }
        )
        total_workload += workload

    # 3. Compute priority_score and sort courses by it descending. A
    #    stable sort keeps input order for ties so scheduling is
    #    deterministic.
    for cp in course_plans:
        workload_weight = cp["workload"] / total_workload if total_workload > 0 else 0.0
        cp["priority_score"] = compute_priority_score(
            deadline_urgency=cp["deadline_urgency"],
            workload_weight=workload_weight,
            weak_point_weight=0.0,  # no weak-point data yet
            user_priority=cp["user_priority"],
        )
    course_plans.sort(key=lambda cp: -cp["priority_score"])

    # 4. Build the day list from today to the latest deadline. If the
    #    latest deadline is in the past we still keep one day so tasks
    #    are scheduled rather than silently dropped.
    latest_deadline = max(cp["deadline"] for cp in course_plans)
    days: list[date] = []
    cursor = today
    while cursor <= latest_deadline:
        days.append(cursor)
        cursor += timedelta(days=1)
    if not days:
        days.append(today)

    daily_remaining: dict[date, int] = {d: daily_minutes for d in days}
    # Per-(course_id, date) remaining minutes under the 90-min cap.
    per_course_day_remaining: dict[tuple[int, date], int] = {}

    schedule: list[dict[str, Any]] = []

    for cp in course_plans:
        # Sort tasks within the course by priority desc (high first);
        # stable so equal-priority tasks keep the planner's order.
        ordered_tasks = sorted(
            cp["tasks"],
            key=lambda t: -int(t.get("priority", 0) or 0),
        )

        for task in ordered_tasks:
            estimate = int(task.get("estimate_minutes", 0) or 0)
            if estimate <= 0:
                continue

            chosen: date | None = None
            for d in days:
                if d > cp["deadline"]:
                    break
                cap_key = (cp["course_id"], d)
                if cap_key not in per_course_day_remaining:
                    per_course_day_remaining[cap_key] = _PER_COURSE_DAILY_CAP_MIN
                if (
                    daily_remaining[d] >= estimate
                    and per_course_day_remaining[cap_key] >= estimate
                ):
                    chosen = d
                    break

            # Fallback: place on the last day within the deadline (or the
            # last available day overall) so the task is never dropped.
            if chosen is None:
                valid = [d for d in days if d <= cp["deadline"]]
                chosen = valid[-1] if valid else days[-1]
                cap_key = (cp["course_id"], chosen)
                if cap_key not in per_course_day_remaining:
                    per_course_day_remaining[cap_key] = _PER_COURSE_DAILY_CAP_MIN

            daily_remaining[chosen] -= estimate
            per_course_day_remaining[(cp["course_id"], chosen)] -= estimate

            schedule.append(
                {
                    "scheduled_date": chosen,
                    "course_id": cp["course_id"],
                    "course_name": cp["course_name"],
                    "title": task.get("title", ""),
                    "task_type": task.get("task_type", "review"),
                    "estimate_minutes": estimate,
                    "priority": int(task.get("priority", 3) or 3),
                    "acceptance": task.get("acceptance", ""),
                    "start_time": None,
                    "end_time": None,
                }
            )

    schedule.sort(key=lambda item: item["scheduled_date"])
    return schedule


__all__ = ["compute_priority_score", "schedule_multi_courses"]
