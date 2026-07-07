"""Schemas for conversation message history replay (T04)."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class CitationBrief(BaseModel):
    """精简引用信息，用于历史回放（不含 chunk 全文，避免响应过大）。"""
    chunk_id: int
    quote_text: Optional[str] = None
    page_no: Optional[int] = None
    material_name: Optional[str] = None
    display_label: Optional[str] = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: Optional[str] = None
    answer_json: Optional[str] = None
    citations: List[CitationBrief] = []
    created_at: datetime


class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    total: int
