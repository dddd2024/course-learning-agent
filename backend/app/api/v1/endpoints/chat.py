"""Chat endpoint — answer a student question within a conversation.

The flow:
1. Validate that the conversation belongs to the current user (and the
   course_id matches) — cross-user access returns 404.
2. Persist the user's question as a ``user`` message.
3. Keyword-retrieve chunks for the question (top_k=12), then re-rank
   and keep the top 6.
4. Run :func:`CourseQAAgent.answer_question` to generate a structured,
   citation-grounded answer.
5. Persist the assistant's answer (text + full JSON) as an
   ``assistant`` message.
6. Return a :class:`ChatResponse` with the enriched citations.

Every run is traced via :class:`AgentAudit` so the operator can replay
retrieve / generate / validate steps later. Audit failures are
swallowed so they never break the main flow.
"""
import json
import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.agents.course_qa import answer_question
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.citation import Citation
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.user import User
from app.retrieval.search import keyword_search, rerank
from app.schemas.chat import ChatRequest, ChatResponse, CitationItem
from app.services.llm_config_service import (
    build_user_config,
    get_active_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_PROMPT_VERSION = "course_qa_v1"


def _get_owned_conversation(
    db: Session, conversation_id: int, course_id: int, user_id: int
) -> Conversation:
    """Return the conversation if it belongs to ``user_id`` and matches
    ``course_id``; otherwise raise 404 so existence is never leaked."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .first()
    )
    if conversation is None or conversation.course_id != course_id:
        raise NotFoundException(message="对话不存在")
    return conversation


def _summarise(text: str, limit: int = 200) -> str:
    """Truncate ``text`` to ``limit`` chars for audit summaries."""
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "..."


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """Answer a question within a conversation owned by the current user."""
    conversation = _get_owned_conversation(
        db, payload.conversation_id, payload.course_id, current_user.id
    )

    # Read the user's active LLM config so the agent prefers it over the
    # system provider. ``provider`` / ``config_id`` / ``model_name``
    # trace which LLM backed the call in the audit record.
    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None
    provider = (
        "user"
        if active_config
        else ("real" if settings.LLM_PROVIDER == "real" else "mock")
    )
    config_id = active_config.id if active_config else None
    model_name = active_config.model if active_config else settings.LLM_MODEL

    # Open an audit run for this course_qa invocation. The audit is
    # observability only — every audit call is wrapped in try/except so
    # an audit failure never breaks the chat flow.
    run_started_at = time.monotonic()
    run_id: int | None = None
    try:
        run = AgentAudit.create_run(
            db,
            user_id=current_user.id,
            run_type="course_qa",
            input_summary={"question": _summarise(payload.question, 200)},
            prompt_version=_PROMPT_VERSION,
            model_name=model_name,
            provider=provider,
            config_id=config_id,
        )
        run_id = run.id
        db.commit()
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.create_run failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    # 1. Persist the user's question.
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.question,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # 2. Retrieve + rerank chunks scoped to the course.
    retrieve_started = time.monotonic()
    retrieve_top_k = 12
    rerank_top_k = 6
    candidates = keyword_search(
        db, payload.course_id, payload.question, top_k=retrieve_top_k
    )
    ranked = rerank(payload.question, candidates, top_k=rerank_top_k)
    retrieve_duration = int((time.monotonic() - retrieve_started) * 1000)
    # Task 19.1: record detailed retrieve step data so the operator can
    # replay the retrieval trace (query / top_k / per-chunk score+snippet).
    retrieve_input = {
        "query": _summarise(payload.question, 200),
        "course_id": payload.course_id,
        "top_k": retrieve_top_k,
        "filters": {"material_status": "ready"},
    }
    retrieve_output = {
        "total": len(ranked),
        "items": [
            {
                "chunk_id": c["chunk_id"],
                "score": c.get("score", 0),
                "title": c.get("title"),
                "page_no": c.get("page_no"),
                "snippet": (c.get("text", "") or "")[:80],
            }
            for c in ranked
        ],
    }
    _safe_add_step(
        db,
        run_id=run_id,
        step_name="retrieve",
        step_index=0,
        input_data=retrieve_input,
        output_data=retrieve_output,
        duration_ms=retrieve_duration,
    )

    # 3. Generate the structured answer.
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    course_name = course.name if course else ""
    generate_started = time.monotonic()
    try:
        result = answer_question(
            db,
            payload.course_id,
            payload.question,
            ranked,
            course_name,
            user_config=user_config,
        )
    except Exception as exc:
        _safe_finish_run(
            db,
            run_id=run_id,
            status="failed",
            error_message=str(exc),
            started_at=run_started_at,
        )
        raise
    generate_duration = int((time.monotonic() - generate_started) * 1000)
    _safe_add_step(
        db,
        run_id=run_id,
        step_name="generate",
        step_index=1,
        input_data={"prompt_version": _PROMPT_VERSION},
        output_data={"answer": _summarise(result.get("answer", ""), 200)},
        duration_ms=generate_duration,
    )

    # 4. Persist the assistant's answer (text + full JSON payload).
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.get("answer", ""),
        answer_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    # 5. Enrich citations with material metadata for the response.
    chunk_map = {c["chunk_id"]: c for c in ranked}
    citations: list[CitationItem] = []
    for cite in result.get("citations", []):
        chunk = chunk_map.get(cite.get("chunk_id"))
        if chunk is None:
            continue
        page_no = chunk.get("page_no")
        quote_text = cite.get("quote_text", "")
        confidence = cite.get("confidence", 0.0)
        citations.append(
            CitationItem(
                chunk_id=cite["chunk_id"],
                material_name=chunk.get("filename", ""),
                page_no=page_no,
                quote_text=quote_text,
                confidence=confidence,
            )
        )
        # Persist the citation so it can be re-fetched later via
        # GET /messages/{id}/citations without replaying retrieval.
        db.add(
            Citation(
                message_id=assistant_msg.id,
                chunk_id=cite["chunk_id"],
                quote_text=quote_text,
                confidence=confidence,
                page_no=page_no,
            )
        )
    db.commit()

    # Validate step: log how many citations survived verification.
    _safe_add_step(
        db,
        run_id=run_id,
        step_name="validate",
        step_index=2,
        input_data={"retrieved_chunk_count": len(ranked)},
        output_data={"citation_count": len(citations)},
        duration_ms=0,
    )

    total_duration = int((time.monotonic() - run_started_at) * 1000)
    _safe_finish_run(
        db,
        run_id=run_id,
        status="success",
        output_summary={
            "answer": _summarise(result.get("answer", ""), 200),
            "citation_count": len(citations),
            "not_found": bool(result.get("not_found", False)),
        },
        duration_ms=total_duration,
    )

    return ChatResponse(
        message_id=assistant_msg.id,
        answer=result.get("answer", ""),
        citations=citations,
        not_found=result.get("not_found", False),
        follow_up_questions=result.get("follow_up_questions", []),
        agent_run_id=run_id,
        reliability_level=result.get("reliability_level", "medium"),
        retrieved_chunks=result.get("retrieved_chunks", []),
    )


def _safe_add_step(
    db: Session,
    run_id: int | None,
    step_name: str,
    step_index: int,
    input_data=None,
    output_data=None,
    duration_ms: int | None = None,
    status: str = "success",
) -> None:
    """Add an audit step, swallowing any error so the main flow runs on."""
    if run_id is None:
        return
    try:
        AgentAudit.add_step(
            db,
            run_id=run_id,
            step_name=step_name,
            step_index=step_index,
            input_data=input_data,
            output_data=output_data,
            duration_ms=duration_ms,
            status=status,
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.add_step(%s) failed: %s", step_name, exc)
        try:
            db.rollback()
        except Exception:
            pass


def _safe_finish_run(
    db: Session,
    run_id: int | None,
    status: str,
    output_summary=None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    started_at: float | None = None,
) -> None:
    """Finish an audit run, swallowing any error so the main flow runs on."""
    if run_id is None:
        return
    if duration_ms is None and started_at is not None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
    try:
        AgentAudit.finish_run(
            db,
            run_id=run_id,
            status=status,
            output_summary=output_summary,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.finish_run failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
