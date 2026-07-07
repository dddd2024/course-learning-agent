"""Pydantic schemas for the multi-course planning endpoint."""
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MultiCourseInput(BaseModel):
    """A single course entry in a POST /plans/multi request.

    ``user_priority`` 兼容两种输入：
    - 新格式：0-1 的浮点数（如 0.8），直接生效
    - 旧格式：1-5 的整数（如 4），由 API 层归一化为 0-1

    旧前端发送的 ``priority`` 字段通过 ``AliasChoices`` 被接受并
    映射到 ``user_priority``，避免历史 payload 失效。
    """

    course_id: int
    deadline: date
    user_priority: Optional[float] = Field(
        default=None,
        ge=0,
        le=5,
        validation_alias=AliasChoices("user_priority", "priority"),
    )


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
