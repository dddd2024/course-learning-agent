"""Pydantic schemas for the knowledge-point endpoints."""
from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


class KnowledgePointResponse(BaseModel):
    """A single knowledge point returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    summary: Optional[str] = None
    importance: int
    source_chunk_ids: List[int] = []
    exam_style: Optional[str] = None
    review_action: Optional[str] = None
    parent_id: Optional[int] = None
    status: Optional[str] = "active"
    stable_key: Optional[str] = None
    generation: int = 1

    @field_validator("source_chunk_ids", mode="before")
    @classmethod
    def _parse_source_chunk_ids(cls, value):
        """Parse the JSON string stored in the DB into a list of ints."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
        if value is None:
            return []
        return list(value)


class KnowledgePointListResponse(BaseModel):
    """List of knowledge points for a course."""

    items: List[KnowledgePointResponse]
    total: int


class GenerateKnowledgePointsResponse(BaseModel):
    """Result of POST /courses/{id}/knowledge-points/generate."""

    knowledge_points: List[KnowledgePointResponse]
    count: int = 0
    requested: int = 0
    generated: int = 0
    dropped: int = 0
    drop_reasons: List[str] = []
    generation: int = 1
    archived_count: int = 0
