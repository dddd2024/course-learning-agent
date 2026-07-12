"""Pydantic schemas for the study-plan and todo endpoints."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    PLAN-V3-01: execution fields (``target_type``, ``target_id``,
    ``target_spec``, ``execution_status``, ``verification_method``,
    ``verification_result``, ``started_at``, ``completed_at``,
    ``last_action_at``) are now exposed so the frontend can drive
    the task lifecycle.
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
    # Execution fields
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    target_spec: Optional[Dict[str, Any]] = None
    execution_status: str = "pending"
    verification_method: Optional[str] = None
    verification_result: Optional[Dict[str, Any]] = None
    auto_completed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_action_at: Optional[datetime] = None

    @field_validator("target_spec", mode="before")
    @classmethod
    def _parse_target_spec(cls, value):
        """Parse the JSON string stored in the DB into a dict."""
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @field_validator("verification_result", mode="before")
    @classmethod
    def _parse_verification_result(cls, value):
        """Parse the JSON string stored in the DB into a dict."""
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, TypeError):
                return None
        return None


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


class TaskVerifyRequest(BaseModel):
    """Payload for POST /plans/tasks/{task_id}/verify."""

    confirmation: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=1000)
    model_config = ConfigDict(extra="forbid")


class TaskEventRequest(BaseModel):
    """A user-confirmed task action recorded as server-side evidence."""

    event_type: str = Field(..., pattern="^(target_loaded|user_confirmed|review_confirmed)$")
    target_id: int = Field(..., gt=0)
    material_version_id: Optional[int] = Field(default=None, gt=0)
    route: Optional[str] = Field(default=None, max_length=500)
    page_count: Optional[int] = Field(default=None, ge=1)
    note: Optional[str] = Field(default=None, max_length=1000)


class TaskOverrideRequest(BaseModel):
    """Payload for POST /plans/tasks/{task_id}/override."""

    reason: str = Field(..., min_length=1)


class GoalUpdate(BaseModel):
    """Payload for PATCH /plans/{goal_id}. All fields optional."""

    status: Optional[str] = None


class TodoListResponse(BaseModel):
    """List of todos for the current user."""

    items: List[TodoResponse]
    total: int
