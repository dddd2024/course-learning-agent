"""Pydantic schemas for the study-plan and todo endpoints."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PlanCreate(BaseModel):
    """Payload for POST /plans."""

    goal: str = Field(..., min_length=1)
    courses: List[str] = Field(..., min_length=1)
    deadline: date
    daily_minutes: int = Field(..., gt=0)


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
    """Result of POST /plans."""

    goal: GoalResponse
    tasks: List[TaskResponse]
    todos: List[TodoResponse]


class TodoUpdate(BaseModel):
    """Payload for PATCH /todos/{id}. All fields optional."""

    status: Optional[str] = None
    actual_minutes: Optional[int] = Field(default=None, ge=0)


class TodoListResponse(BaseModel):
    """List of todos for the current user."""

    items: List[TodoResponse]
    total: int
