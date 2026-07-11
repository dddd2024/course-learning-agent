"""Pydantic schemas for the study-plan and todo endpoints."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanCreate(BaseModel):
    """Payload for POST /plans."""

    goal: str = Field(..., min_length=1)
    # ``course_ids`` is the preferred, unambiguous contract.  ``courses`` is
    # retained for older clients that still submit display names.
    course_ids: List[int] = Field(default_factory=list)
    courses: List[str] = Field(default_factory=list)
    deadline: date
    daily_minutes: int = Field(..., gt=0)

    @model_validator(mode="after")
    def require_courses(self) -> "PlanCreate":
        """Require at least one course via the new or legacy field."""
        if not self.course_ids and not self.courses:
            raise ValueError("请至少选择一门课程")
        return self


class GoalResponse(BaseModel):
    """The ``goal`` block of a PlanResponse."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    deadline: date
    daily_minutes: int
    status: str


class TaskResponse(BaseModel):
    """A single decomposed study task.

    ``course_name`` is denormalised on the way out (looked up from
    ``Course.name``) so the frontend does not need a second round-trip.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    course_id: int
    course_name: str = ""
    title: str
    task_type: str
    estimate_minutes: int
    priority: int
    acceptance: Optional[str] = None
    status: str


class TodoResponse(BaseModel):
    """A single scheduled todo item.

    ``course_name`` is denormalised on the way out (looked up from
    ``Course.name``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    task_id: int
    course_id: int
    course_name: str = ""
    title: str
    scheduled_date: date
    scheduled_start: Optional[time] = None
    scheduled_end: Optional[time] = None
    estimate_minutes: int
    status: str
    actual_minutes: Optional[int] = None
    completed_at: Optional[datetime] = None


class PlanResponse(BaseModel):
    """A complete persisted plan returned by create/read endpoints."""

    goal: GoalResponse
    tasks: List[TaskResponse]
    todos: List[TodoResponse]
    unscheduled_tasks: List[dict] = []


class PlanProgressResponse(BaseModel):
    """Compact task/todo progress shown in the plan history list."""

    tasks_total: int
    tasks_completed: int
    todos_total: int
    todos_completed: int


class PlanSummaryResponse(BaseModel):
    """A persisted learning goal plus enough context to choose it."""

    goal: GoalResponse
    course_ids: List[int]
    course_names: List[str]
    progress: PlanProgressResponse
    created_at: datetime
    updated_at: datetime


class PlanListResponse(BaseModel):
    """All persisted learning goals owned by the current user."""

    items: List[PlanSummaryResponse]
    total: int


class TodoUpdate(BaseModel):
    """Payload for PATCH /todos/{id}. All fields optional."""

    status: Optional[str] = None
    actual_minutes: Optional[int] = Field(default=None, ge=0)


class TaskUpdate(BaseModel):
    """Payload for PATCH /plans/tasks/{task_id}. All fields optional."""

    status: Optional[str] = None


class GoalUpdate(BaseModel):
    """Payload for PATCH /plans/{goal_id}. All fields optional."""

    status: Optional[str] = None


class TodoListResponse(BaseModel):
    """List of todos for the current user."""

    items: List[TodoResponse]
    total: int
