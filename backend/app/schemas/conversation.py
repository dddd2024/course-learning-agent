"""Pydantic schemas for the conversation endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class ConversationListResponse(BaseModel):
    """List of conversations for a course."""

    items: List[ConversationResponse]
    total: int
