"""Pydantic schemas for the search endpoint."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class SearchResultItem(BaseModel):
    """A single chunk returned by the search endpoint."""

    chunk_id: int
    material_id: int
    filename: str
    page_no: Optional[int] = None
    title: Optional[str] = None
    text: str
    snippet: Optional[str] = ""
    score: float
    retrieval_mode: str = "keyword_fallback"


class SearchResultListResponse(BaseModel):
    """Response shape for ``GET /api/v1/search``."""

    items: List[SearchResultItem]
    total: int
