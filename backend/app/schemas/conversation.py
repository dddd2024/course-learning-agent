"""Pydantic schemas for the conversation endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.timezone import ensure_utc


class ConversationCreate(BaseModel):
    """Payload for POST /conversations. ``user_id`` is bound server-side."""

    course_id: int
    title: Optional[str] = Field(default=None, max_length=255)


class ConversationUpdate(BaseModel):
    """Payload for PATCH /conversations/{id} — currently only renames."""

    title: str = Field(..., min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    """Conversation fields returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # SQLite strips tzinfo from DateTime(timezone=True) columns on read,
    # so a datetime loaded from the DB is naive even though it was
    # stored as aware UTC. Pydantic would then serialize it without an
    # offset, and the browser's new Date(...) would treat it as local
    # time (8-hour skew for UTC+8 clients). Attach UTC tzinfo before
    # serialization so the API always emits an explicit offset.
    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _attach_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return ensure_utc(value)


class ConversationListResponse(BaseModel):
    """List of conversations for a course."""

    items: List[ConversationResponse]
    total: int
