"""Chat endpoints — answer a student question within a conversation.

Phase 2 Task B: the core pipeline lives in :mod:`app.services.chat_service`
so both POST /chat (sync) and POST /chat/stream (SSE) share the same logic.

The flow:
1. Validate that the conversation belongs to the current user.
2. Persist the user's question.
3. Retrieve + rerank chunks.
4. Generate the answer via CourseQAAgent.
5. Persist the assistant message + citations.
6. Return / stream the ChatResponse.

Every run is traced via AgentAudit; failures are logged to agent_error_logs.
"""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import run_chat_pipeline, validate_chat_request, validate_selection_context

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """Answer a question within a conversation owned by the current user."""
    # Validate ownership synchronously so 404 is returned before any work.
    validate_chat_request(db, current_user, payload.course_id,
                          payload.conversation_id)
    selection_context = payload.selection_context.model_dump() if payload.selection_context else None
    validate_selection_context(db, current_user, payload.course_id, selection_context)
    final_data: dict | None = None
    for event in run_chat_pipeline(
        db, current_user, payload.course_id,
        payload.conversation_id, payload.question, selection_context,
    ):
        if event["event"] == "final":
            final_data = event["data"]
    if final_data is None:
        # A step_error occurred before final — build a minimal failure response.
        return ChatResponse(
            message_id=0,
            answer="回答生成失败，请稍后重试或检查个人中心 LLM 配置。",
            citations=[],
            not_found=True,
            follow_up_questions=[],
            reliability_level="failed",
            retrieved_chunks=[],
        )
    return ChatResponse(**final_data)


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream chat progress as SSE events.

    Event types:
    - step_started: {"step": "retrieve", "message": "..."}
    - step_done: {"step": "retrieve", "summary": {...}}
    - step_error: {"step": "generate", "message": "...", "advice": "..."}
    - final: {"data": <ChatResponse>}
    """
    # Validate ownership synchronously so a 404 is returned with the
    # proper status code BEFORE the StreamingResponse starts sending.
    # Once the SSE response begins, the status code can no longer change.
    validate_chat_request(db, current_user, payload.course_id,
                          payload.conversation_id)
    selection_context = payload.selection_context.model_dump() if payload.selection_context else None
    validate_selection_context(db, current_user, payload.course_id, selection_context)

    def event_generator():
        for event in run_chat_pipeline(
            db, current_user, payload.course_id,
            payload.conversation_id, payload.question, selection_context,
        ):
            event_type = event.get("event", "message")
            data = {k: v for k, v in event.items() if k != "event"}
            yield f"event: {event_type}\n"
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
