"""Pydantic schemas for the multi-course planning endpoint."""
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MultiCourseInput(BaseModel):
    """A single course entry in a POST /plans/multi request."""

    course_id: int
    deadline: date
    user_priority: Optional[float] = Field(default=None, ge=0, le=1)


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


class MultiPlanResponse(BaseModel):
    """Result of POST /plans/multi."""

    schedule: List[MultiScheduleItem]
    overflow_warnings: List[str] = Field(default_factory=list)
