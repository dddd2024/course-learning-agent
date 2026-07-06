"""Pydantic schemas for the agent-run audit endpoints."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


def _maybe_parse_json(value: Any) -> Any:
    """Best-effort parse a JSON string back to a Python object."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


class AgentStepResponse(BaseModel):
    """A single step within an agent run."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    step_name: str
    step_index: int
    input_data: Optional[Any] = None
    output_data: Optional[Any] = None
    duration_ms: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("input_data", "output_data", mode="before")
    @classmethod
    def _parse_json_field(cls, value):
        return _maybe_parse_json(value)


class AgentRunResponse(BaseModel):
    """A single agent run (no steps)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    run_type: str
    status: str
    input_summary: Optional[Any] = None
    output_summary: Optional[Any] = None
    prompt_version: Optional[str] = None
    model_name: Optional[str] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @field_validator("input_summary", "output_summary", mode="before")
    @classmethod
    def _parse_summary_field(cls, value):
        return _maybe_parse_json(value)


class AgentRunDetailResponse(AgentRunResponse):
    """Agent run detail including its step list."""

    steps: List[AgentStepResponse] = []


class AgentRunListResponse(BaseModel):
    """Paginated list of agent runs for the current user."""

    items: List[AgentRunResponse]
    total: int
