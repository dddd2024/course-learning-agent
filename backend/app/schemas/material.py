"""Pydantic schemas for the material endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.timezone import ensure_utc


class MaterialResponse(BaseModel):
    """Material fields returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    filename: str
    file_type: str
    # Storage paths are intentionally not exposed; clients use this URL with
    # their bearer token to retrieve the original file.
    file_url: Optional[str] = None
    status: str
    version: int
    error_message: Optional[str] = None
    uploaded_at: datetime
    parse_started_at: Optional[datetime] = None
    parse_finished_at: Optional[datetime] = None
    parse_attempts: int = 0
    last_parse_error: Optional[str] = None

    # SQLite strips tzinfo from DateTime(timezone=True) columns on read,
    # so a datetime loaded from the DB is naive even though it was
    # stored as aware UTC. Pydantic would then serialize it without an
    # offset, and the browser's new Date(...) would treat it as local
    # time (8-hour skew for UTC+8 clients). Attach UTC tzinfo before
    # serialization so the API always emits an explicit offset.
    @field_validator(
        "uploaded_at",
        "parse_started_at",
        "parse_finished_at",
        mode="before",
    )
    @classmethod
    def _attach_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return ensure_utc(value)


class MaterialListResponse(BaseModel):
    """List of materials for a course."""

    items: List[MaterialResponse]
    total: int


class ParseResponse(BaseModel):
    """Result of POST /materials/{id}/parse."""

    material_id: int
    status: str
    chunk_count: int


class ImageResponse(BaseModel):
    """An image extracted from a PDF material."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    page_no: int
    status: str = "ready"  # loading/ready/missing/forbidden/error
    missing_reason: Optional[str] = None
    file_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = "png"
    is_decorative: bool = False
    decorative_reason: Optional[str] = None
    color_variance: Optional[float] = None
    coverage_ratio: Optional[float] = None


class ChunkResponse(BaseModel):
    """A single material chunk returned by the chunks endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int
    chunk_index: int
    text: str
    raw_text: Optional[str] = None
    cleaner_version: Optional[str] = None
    noise_score: Optional[float] = None
    is_indexable: bool = True
    title: Optional[str] = None
    page_no: Optional[int] = None
    token_count: Optional[int] = None
    char_count: Optional[int] = None
    estimated_token_count: Optional[int] = None
    images: List[ImageResponse] = []
    quality_score: Optional[float] = None
    quality_reason: Optional[str] = None
    # LEARN-V3-01: JSON dict of noise types detected (line_repetition,
    # short_line_stacking, low_diversity) or None when the chunk is clean.
    noise_flags: Optional[str] = None


class ChunkListResponse(BaseModel):
    """Paginated list of chunks for a material."""

    items: List[ChunkResponse]
    total: int
    page: int
    page_size: int
