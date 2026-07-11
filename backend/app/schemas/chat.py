"""Pydantic schemas for the chat endpoint."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload for POST /chat."""

    course_id: int
    conversation_id: int
    question: str = Field(..., min_length=1, max_length=4000)


class CitationItem(BaseModel):
    """A single citation returned in a chat answer."""

    chunk_id: int
    material_name: str
    page_no: Optional[int] = None
    quote_text: str = ""
    claim_text: str = ""
    support_status: str = "weak"
    verification_reason: str = ""
    verifier_version: str = ""
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
    # T05: LLM fallback visibility — lets the frontend warn the user
    # when a real-LLM call failed and the answer came from the mock.
    provider: str = "mock"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    # CHAT-V3-01: expose the original and resolved query for audit.
    # The resolved query was used for retrieval; the original is what the
    # user typed. Both are optional for backward compatibility.
    original_query: Optional[str] = None
    resolved_query: Optional[str] = None
