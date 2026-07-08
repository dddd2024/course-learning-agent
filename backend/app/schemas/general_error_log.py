"""Pydantic schemas for the general error log center."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ErrorLogResponse(BaseModel):
    """A single error log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    category: str
    level: str
    status: str
    title: str
    message: str
    technical_detail: Optional[str] = None
    course_id: Optional[int] = None
    material_id: Optional[int] = None
    agent_run_id: Optional[int] = None
    request_path: Optional[str] = None
    retry_count: int = 0
    max_retries: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ErrorLogListResponse(BaseModel):
    """Paginated list of error logs for the current user."""

    items: List[ErrorLogResponse]
    total: int
    page: int
    page_size: int


class ErrorLogResolveRequest(BaseModel):
    """Body for POST /logs/{id}/resolve."""

    status: str = "resolved"  # resolved / ignored
