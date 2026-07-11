"""Pydantic schemas for the agent-run audit endpoints."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


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
    # V3-02: provider / model traceability fields
    provider: Optional[str] = None
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    actual_provider: Optional[str] = None
    actual_model: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    fallback_chain: Optional[Any] = None
    evidence_status: Optional[str] = None
    # final_status mirrors status but makes the "definitive outcome"
    # semantics explicit for the frontend.
    final_status: Optional[str] = None
    config_id: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @field_validator("input_summary", "output_summary", "fallback_chain", mode="before")
    @classmethod
    def _parse_json_field(cls, value):
        return _maybe_parse_json(value)

    @field_validator("fallback_used", mode="before")
    @classmethod
    def _coerce_bool(cls, value):
        """SQLite stores booleans as 0/1 integers."""
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return bool(value)

    @field_validator("final_status", mode="before")
    @classmethod
    def _default_final_status(cls, value):
        """If final_status is not explicitly set, default to status."""
        return value

    @model_validator(mode="after")
    def _populate_final_status(self):
        """Ensure final_status is populated with the run's status."""
        if not self.final_status:
            self.final_status = self.status
        return self


class AgentRunDetailResponse(AgentRunResponse):
    """Agent run detail including its step list."""

    steps: List[AgentStepResponse] = []


class AgentRunListResponse(BaseModel):
    """Paginated list of agent runs for the current user."""

    items: List[AgentRunResponse]
    total: int
