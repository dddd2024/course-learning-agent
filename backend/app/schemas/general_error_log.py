"""Pydantic schemas for the general error log center."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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


# Task A: frontend error reporting. Categories are deliberately broader
# than the server-side defaults so the frontend can classify its own
# failures (a network error vs an API 500 vs a parse error). Using
# ``Literal`` makes Pydantic reject unknown categories with 422.
_FrontendErrorCategory = Literal[
    "upload", "parse", "agent", "search", "system",
    "frontend", "network", "api",
]
_FrontendErrorLevel = Literal["warning", "error"]


class FrontendErrorReportRequest(BaseModel):
    """Body for POST /logs (frontend error reporting, Task A).

    The frontend reports failed API/network requests so the log center
    can show them. ``message`` and ``technical_detail`` are redacted by
    :func:`app.services.error_logger.log_error` before persistence.
    """

    category: _FrontendErrorCategory
    level: _FrontendErrorLevel = "error"
    title: str = Field(..., max_length=255)
    message: str = Field(..., min_length=1)
    technical_detail: Optional[str] = None
    request_path: Optional[str] = Field(None, max_length=255)
    frontend_route: Optional[str] = Field(None, max_length=255)
    status_code: Optional[int] = None
