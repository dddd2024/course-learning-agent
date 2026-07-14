"""Schemas for conversation message history replay (T04)."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.timezone import ensure_utc


class CitationBrief(BaseModel):
    """精简引用信息，用于历史回放（不含 chunk 全文，避免响应过大）。"""
    chunk_id: int
    quote_text: Optional[str] = None
    page_no: Optional[int] = None
    material_name: Optional[str] = None
    material_public_id: Optional[str] = None
    display_label: Optional[str] = None
    claim_text: Optional[str] = None
    support_status: str = "weak"
    verification_reason: Optional[str] = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: Optional[str] = None
    answer_json: Optional[str] = None
    citations: List[CitationBrief] = []
    created_at: datetime

    # SQLite strips tzinfo from DateTime(timezone=True) columns on read,
    # so a datetime loaded from the DB is naive even though it was
    # stored as aware UTC. Pydantic would then serialize it without an
    # offset, and the browser's new Date(...) would treat it as local
    # time (8-hour skew for UTC+8 clients). Attach UTC tzinfo before
    # serialization so the API always emits an explicit offset.
    @field_validator("created_at", mode="before")
    @classmethod
    def _attach_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return ensure_utc(value)


class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    total: int
