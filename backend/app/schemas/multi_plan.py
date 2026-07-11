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
    """Result of POST /plans/multi."""

    schedule: List[MultiScheduleItem]
    overflow_warnings: List[str] = Field(default_factory=list)
    unscheduled_tasks: List[MultiUnscheduledTask] = Field(default_factory=list)
