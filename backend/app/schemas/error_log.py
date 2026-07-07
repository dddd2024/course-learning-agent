"""Pydantic schemas for agent error logs (Phase 2 Task E)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class AgentErrorLogResponse(BaseModel):
    """A single agent error log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    conversation_id: Optional[int] = None
    request_id: Optional[str] = None
    step: str
    provider: Optional[str] = None
    model: Optional[str] = None
    config_id: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback_summary: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_status: str = "unresolved"


class AgentErrorLogListResponse(BaseModel):
    """Paginated list of agent error logs for the current user."""

    items: List[AgentErrorLogResponse]
    total: int
