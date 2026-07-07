"""Pydantic schemas for the chat endpoint."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload for POST /chat."""

    course_id: int
    conversation_id: int
    question: str = Field(..., min_length=1)


class CitationItem(BaseModel):
    """A single citation returned in a chat answer."""

    chunk_id: int
    material_name: str
    page_no: Optional[int] = None
    quote_text: str = ""
    confidence: float = 0.0
    # Phase 2 Task A: pre-assembled label for capsule display
    # (e.g. "操作系统讲义.pdf · 第 12 页"). Backend-assembled so the
    # frontend renders capsules without repeating formatting logic.
    display_label: str = ""


class RetrievedChunkItem(BaseModel):
    """A retrieved chunk shown in the retrieval visualisation drawer.

    Task 19: ``is_cited`` tells the frontend whether this chunk was
    referenced by at least one citation in the answer.
    """

    chunk_id: int
    score: float = 0.0
    title: Optional[str] = None
    page_no: Optional[int] = None
    snippet: str = ""
    is_cited: bool = False


class ChatResponse(BaseModel):
    """Response shape for POST /chat."""

    message_id: int
    answer: str
    citations: List[CitationItem]
    not_found: bool
    follow_up_questions: List[str]
    agent_run_id: Optional[int] = None
    # Task 20: reliability level (failed / low / medium / high).
    reliability_level: str = "medium"
    # Task 19: top-K retrieved chunks with is_cited flag.
    retrieved_chunks: List[RetrievedChunkItem] = Field(default_factory=list)
