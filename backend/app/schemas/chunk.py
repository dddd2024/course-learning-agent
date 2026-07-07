"""Pydantic schemas for the chunks endpoint (Phase 2 Task A)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChunkDetailResponse(BaseModel):
    """Full chunk detail returned by GET /api/v1/chunks/{chunk_id}.

    Ownership is verified through the ``chunk -> material -> course ->
    user_id`` chain so a user can only fetch their own chunks;
    cross-user access returns 404 (existence is never leaked).
    """

    chunk_id: int
    material_id: int
    material_name: str = ""
    title: Optional[str] = None
    page_no: Optional[int] = None
    text: str
