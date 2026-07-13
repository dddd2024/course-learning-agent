"""Pydantic schemas for the multi-course planning endpoint."""
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _normalize_priority_input(data: Any) -> Any:
    """T0-1: 区分 priority（旧 1-5）与 user_priority（新 0-1）。

    - 旧字段 priority（1-5）除以 5 归一化为 0-1
    - 新字段 user_priority（0-1）保持不变
    - 两者都提供时优先 user_priority
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if data.get("user_priority") is not None:
        return data
    if data.get("priority") is not None:
        try:
            v = float(data["priority"])
            # 旧字段范围 1-5，归一化为 0-1
            data["user_priority"] = v / 5.0
        except (TypeError, ValueError):
            pass
    return data


class MultiCourseInput(BaseModel):
    """A single course entry in a POST /plans/multi request.

    ``user_priority`` 兼容两种输入：
    - 新格式：0-1 的浮点数（如 0.8），直接生效
    - 旧格式：1-5 的整数（如 4），由 ``_normalize_priority_input``
      归一化为 0-1（如 4 → 0.8，1 → 0.2）

    旧前端发送的 ``priority`` 字段通过 ``model_validator(mode="before")``
    被接受并归一化，避免历史 payload 失效，也避免 1-5 的值被
    误当成已归一化的 0-1 值。
    """

    course_id: int
    deadline: date
    user_priority: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize_priority(cls, data: Any) -> Any:
        return _normalize_priority_input(data)


class MultiPlanCreate(BaseModel):
    """Payload for POST /plans/multi."""

    courses: List[MultiCourseInput] = Field(..., min_length=1)
    daily_minutes: int = Field(..., gt=0)
    constraints: Optional[Dict[str, Any]] = Field(default_factory=dict)


class MultiScheduleItem(BaseModel):
    """A single scheduled todo in a MultiPlanResponse."""

    model_config = ConfigDict(from_attributes=True)

    scheduled_date: date
    course_name: str = ""
    title: str
    estimate_minutes: int
    start_time: Optional[time] = None
    end_time: Optional[time] = None


class MultiUnscheduledTask(BaseModel):
    """A task that was deliberately not persisted because it cannot fit."""

    course_name: str = ""
    title: str
    estimate_minutes: int
    deadline: date
    remaining_budget: int = 0
    reason: str
    suggestion: str


class MultiPlanResponse(BaseModel):
    """Result of POST /plans/multi.

    V6-40: ``multi_plan_id`` is returned so the client can subsequently
    GET / PATCH / DELETE / reschedule the created plan.
    """

    multi_plan_id: Optional[int] = None
    schedule: List[MultiScheduleItem]
    overflow_warnings: List[str] = Field(default_factory=list)
    unscheduled_tasks: List[MultiUnscheduledTask] = Field(default_factory=list)


class MultiPlanTaskItem(BaseModel):
    """A task belonging to a multi-course plan (GET detail response).

    Combines the ``MultiCoursePlanTask`` schedule metadata with the
    ``StudyTask`` title so the frontend can render the full plan without
    extra round-trips.
    """

    task_id: Optional[int] = None
    course_id: int
    course_name: str = ""
    title: str = ""
    scheduled_date: Optional[date] = None
    estimate_minutes: int = 0
    unscheduled_reason: Optional[str] = None
    task_status: Optional[str] = None
    generation: Optional[int] = None


class MultiPlanDetailResponse(BaseModel):
    """Response for GET /plans/multi/{multi_plan_id}.

    Includes the plan metadata (id, title, status, deadline,
    daily_minutes) and a flat list of all tasks with their schedule
    info.
    """

    id: int
    title: str
    status: str
    deadline: date
    daily_minutes: int
    generation_version: int = 1
    tasks: List[MultiPlanTaskItem] = Field(default_factory=list)


class MultiPlanListItem(BaseModel):
    """A multi-plan summary in the list response."""

    id: int
    title: str
    status: str
    deadline: date
    daily_minutes: int
    generation_version: int = 1
    task_count: int = 0


class MultiPlanHistoryItem(BaseModel):
    """A historical task entry in the history response."""

    task_id: Optional[int] = None
    course_id: int
    course_name: str = ""
    title: str = ""
    scheduled_date: Optional[date] = None
    estimate_minutes: int = 0
    task_status: Optional[str] = None
    generation: Optional[int] = None
    unscheduled_reason: Optional[str] = None


class MultiPlanUpdate(BaseModel):
    """Payload for PATCH /plans/multi/{multi_plan_id}."""

    status: Optional[str] = None


class MultiPlanReschedule(BaseModel):
    """Payload for POST /plans/multi/{multi_plan_id}/reschedule."""

    daily_minutes: int = Field(..., gt=0)


class RescheduleDiffItem(BaseModel):
    """A single item in the five-category reschedule diff.

    V7.4.2-06: Each item carries stable_task_key, old/new IDs, dates,
    generation, and a reason explaining why it was categorized.
    """

    stable_task_key: Optional[str] = None
    old_task_id: Optional[int] = None
    new_task_id: Optional[int] = None
    old_scheduled_date: Optional[date] = None
    new_scheduled_date: Optional[date] = None
    old_generation: Optional[int] = None
    new_generation: Optional[int] = None
    reason: str = ""
    title: str = ""
    course_name: str = ""
    estimate_minutes: int = 0


class MultiPlanRescheduleDiff(BaseModel):
    """V7.4.2-06: Five-category diff between old and new schedule.

    Categories:
    - kept: same stable_task_key, same scheduled_date
    - moved: same stable_task_key, different scheduled_date
    - created: new stable_task_key not in old schedule
    - superseded: old stable_task_key not in new schedule
    - unscheduled: tasks that could not be scheduled
    """

    kept: List[RescheduleDiffItem] = Field(default_factory=list)
    moved: List[RescheduleDiffItem] = Field(default_factory=list)
    created: List[RescheduleDiffItem] = Field(default_factory=list)
    superseded: List[RescheduleDiffItem] = Field(default_factory=list)
    unscheduled: List[RescheduleDiffItem] = Field(default_factory=list)


class MultiPlanRescheduleResponse(BaseModel):
    """Response for POST /plans/multi/{multi_plan_id}/reschedule.

    V7.4.2-06: Includes a five-category diff (kept/moved/created/
    superseded/unscheduled) with stable_task_key and old/new metadata.
    """

    multi_plan_id: Optional[int] = None
    schedule: List[MultiScheduleItem]
    overflow_warnings: List[str] = Field(default_factory=list)
    unscheduled_tasks: List[MultiUnscheduledTask] = Field(default_factory=list)
    diff: MultiPlanRescheduleDiff = Field(default_factory=MultiPlanRescheduleDiff)
