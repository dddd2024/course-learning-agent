"""Pydantic schemas for the course endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CourseBase(BaseModel):
    """Shared course fields."""

    name: str = Field(..., min_length=1, max_length=100)
    teacher: Optional[str] = Field(default=None, max_length=100)
    semester: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=20)


class CourseCreate(CourseBase):
    """Payload for POST /courses. ``user_id`` is bound server-side."""


class CourseUpdate(BaseModel):
    """Payload for PUT /courses/{id}. All fields optional."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    teacher: Optional[str] = Field(default=None, max_length=100)
    semester: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=20)


class CourseResponse(CourseBase):
    """Course fields returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class CourseListResponse(BaseModel):
    """Paginated list of courses."""

    items: List[CourseResponse]
    total: int
    page: int
    page_size: int
