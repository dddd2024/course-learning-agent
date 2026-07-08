"""Pydantic schemas for the material endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class MaterialResponse(BaseModel):
    """Material fields returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    filename: str
    file_type: str
    file_path: str
    status: str
    version: int
    error_message: Optional[str] = None
    uploaded_at: datetime
    parse_started_at: Optional[datetime] = None
    parse_finished_at: Optional[datetime] = None
    parse_attempts: int = 0
    last_parse_error: Optional[str] = None


class MaterialListResponse(BaseModel):
    """List of materials for a course."""

    items: List[MaterialResponse]
    total: int


class ParseResponse(BaseModel):
    """Result of POST /materials/{id}/parse."""

    material_id: int
    status: str
    chunk_count: int


class ChunkResponse(BaseModel):
    """A single material chunk returned by the chunks endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int
    chunk_index: int
    text: str
    title: Optional[str] = None
    page_no: Optional[int] = None
    token_count: Optional[int] = None


class ChunkListResponse(BaseModel):
    """Paginated list of chunks for a material."""

    items: List[ChunkResponse]
    total: int
    page: int
    page_size: int
