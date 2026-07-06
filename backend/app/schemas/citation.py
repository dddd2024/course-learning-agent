"""Pydantic schemas for the citations endpoint."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class CitationResponse(BaseModel):
    """A single citation persisted for an assistant message."""

    chunk_id: int
    material_id: Optional[int] = None
    material_name: str = ""
    page_no: Optional[int] = None
    quote_text: str = ""
    confidence: float = 0.0


class CitationListResponse(BaseModel):
    """Response shape for GET /messages/{message_id}/citations."""

    items: List[CitationResponse]
    total: int
