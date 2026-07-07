"""Chat service — shared logic for POST /chat and POST /chat/stream (Phase 2 Task B).

Both endpoints run the same core pipeline (retrieve → generate → persist →
cite). The difference is only in how progress is reported:
- POST /chat runs synchronously and returns a single JSON response.
- POST /chat/stream emits SSE events (step_started / step_done / step_error / final).

This module exposes :func:`run_chat_pipeline` which yields progress events
as a generator, so the SSE endpoint can stream them and the sync endpoint
can drain them silently.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.agents.course_qa import answer_question
from app.core.config import settings
from app.core.exceptions import NotFoundException
from app.models.citation import Citation
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.error_log import AgentErrorLog
from app.models.user import User
from app.retrieval.search import keyword_search, rerank
from app.schemas.chat import ChatResponse, CitationItem, RetrievedChunkItem
from app.services.llm_config_service import (
    build_user_config,
    get_active_config,
)

logger = logging.getLogger(__name__)
_PROMPT_VERSION = "course_qa_v1"


def _get_owned_conversation(
    db: Session, conversation_id: int, course_id: int, user_id: int
) -> Conversation:
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


def validate_chat_request(
    db: Session, current_user: User, course_id: int, conversation_id: int
) -> None:
    """Eagerly validate that the conversation belongs to the user.

    Called synchronously by both POST /chat and POST /chat/stream so that
    a cross-user / missing conversation raises NotFoundException (→ 404)
    *before* any streaming begins. The SSE endpoint in particular needs
    this because once the StreamingResponse starts sending, the status
    code can no longer be changed by exception handlers.
    """
    _get_owned_conversation(db, conversation_id, course_id, current_user.id)


def _summarise(text: str, limit: int = 200) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "..."


def _safe_add_step(db, run_id, **kw) -> None:
    if run_id is None:
        return
    try:
        AgentAudit.add_step(db, run_id=run_id, **kw)
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("AgentAudit.add_step(%s) failed: %s", kw.get("step_name"), exc)
        try:
            db.rollback()
        except Exception:
            pass


def _safe_finish_run(db, run_id, **kw) -> None:
    if run_id is None:
        return
    try:
        AgentAudit.finish_run(db, run_id=run_id, **kw)
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("AgentAudit.finish_run failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def _should_persist_steps(status: str) -> bool:
    """Decide whether to persist audit steps based on AGENT_TRACE_MODE."""
    mode = settings.AGENT_TRACE_MODE
    if mode == "always":
        return True
    if mode == "off":
        return False
    # default "error": only persist when the run failed
    return status == "failed"


def _log_error(
    db: Session,
    user_id: int,
    conversation_id: int | None,
    step: str,
    provider: str | None,
    model: str | None,
    config_id: int | None,
    exc: Exception,
) -> None:
    """Persist an agent failure to agent_error_logs (best-effort)."""
    try:
        tb = traceback.format_exc()
        db.add(
            AgentErrorLog(
                user_id=user_id,
                conversation_id=conversation_id,
                step=step,
                provider=provider,
                model=model,
                config_id=config_id,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
                traceback_summary=tb[:1000],
            )
        )
        db.commit()
    except Exception:  # pragma: no cover
        try:
            db.rollback()
        except Exception:
            pass


def run_chat_pipeline(
    db: Session,
    current_user: User,
    course_id: int,
    conversation_id: int,
    question: str,
) -> Iterator[dict[str, Any]]:
    """Run the chat pipeline, yielding SSE-compatible event dicts.

    Yields events with shapes:
        {"event": "step_started", "step": "retrieve", "message": "..."}
        {"event": "step_done", "step": "retrieve", "summary": {...}}
        {"event": "step_error", "step": "generate", "message": "...", "advice": "..."}
        {"event": "final", "data": <ChatResponse dict>}
    """
    conversation = _get_owned_conversation(
        db, conversation_id, course_id, current_user.id
    )

    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None
    provider = (
        "user"
        if active_config
        else ("real" if settings.LLM_PROVIDER == "real" else "mock")
    )
    config_id = active_config.id if active_config else None
    model_name = active_config.model if active_config else settings.LLM_MODEL

    run_started_at = time.monotonic()
    run_id: int | None = None
    try:
        run = AgentAudit.create_run(
            db,
            user_id=current_user.id,
            run_type="course_qa",
            input_summary={"question": _summarise(question, 200)},
            prompt_version=_PROMPT_VERSION,
            model_name=model_name,
            provider=provider,
            config_id=config_id,
        )
        run_id = run.id
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("AgentAudit.create_run failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    # 1. Persist the user's question.
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=question,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # 2. Retrieve
    yield {"event": "step_started", "step": "retrieve", "message": "正在检索课程资料"}
    retrieve_started = time.monotonic()
    try:
        candidates = keyword_search(db, course_id, question, top_k=12)
        ranked = rerank(question, candidates, top_k=6)
    except Exception as exc:
        _log_error(db, current_user.id, conversation_id, "retrieve",
                   provider, model_name, config_id, exc)
        _safe_finish_run(db, run_id, status="failed",
                         error_message=str(exc),
                         duration_ms=int((time.monotonic() - run_started_at) * 1000))
        yield {
            "event": "step_error",
            "step": "retrieve",
            "message": f"检索失败：{exc.__class__.__name__}",
            "advice": "请稍后重试，或检查资料是否已解析完成。",
        }
        return
    retrieve_duration = int((time.monotonic() - retrieve_started) * 1000)

    if _should_persist_steps("success"):
        retrieve_items = [
            {
                "chunk_id": c.get("chunk_id"),
                "score": c.get("score", 0),
                "snippet": (c.get("text", "") or "")[:80],
            }
            for c in ranked
        ]
        _safe_add_step(
            db, run_id=run_id, step_name="retrieve", step_index=0,
            input_data={
                "query": _summarise(question, 200),
                "top_k": 12,
            },
            output_data={
                "total": len(ranked),
                "items": retrieve_items,
            },
            duration_ms=retrieve_duration,
        )

    yield {
        "event": "step_done",
        "step": "retrieve",
        "message": f"命中 {len(ranked)} 个资料片段",
        "summary": {"hit_count": len(ranked)},
    }

    # 3. Generate
    yield {"event": "step_started", "step": "generate", "message": "正在调用模型"}
    course = db.query(Course).filter(Course.id == course_id).first()
    course_name = course.name if course else ""
    generate_started = time.monotonic()
    try:
        result = answer_question(
            db, course_id, question, ranked, course_name, user_config=user_config
        )
    except Exception as exc:
        generate_duration = int((time.monotonic() - generate_started) * 1000)
        _log_error(db, current_user.id, conversation_id, "generate",
                   provider, model_name, config_id, exc)
        if _should_persist_steps("failed"):
            _safe_add_step(
                db, run_id=run_id, step_name="generate", step_index=1,
                input_data={"prompt_version": _PROMPT_VERSION},
                output_data={"error": str(exc)[:200]},
                duration_ms=generate_duration,
                status="failed",
                error_message=str(exc),
            )
        _safe_finish_run(db, run_id, status="failed",
                         error_message=str(exc),
                         duration_ms=int((time.monotonic() - run_started_at) * 1000))
        yield {
            "event": "step_error",
            "step": "generate",
            "message": f"调用模型失败：{exc.__class__.__name__}",
            "advice": "检查个人中心 API Key、Base URL 或模型名称是否正确。",
        }
        return
    generate_duration = int((time.monotonic() - generate_started) * 1000)
    if _should_persist_steps("success"):
        _safe_add_step(
            db, run_id=run_id, step_name="generate", step_index=1,
            input_data={"prompt_version": _PROMPT_VERSION},
            output_data={"answer": _summarise(result.get("answer", ""), 200)},
            duration_ms=generate_duration,
        )
    yield {"event": "step_done", "step": "generate", "message": "模型回答已生成"}

    # 4. Persist assistant message + citations
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.get("answer", ""),
        answer_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    chunk_map = {c["chunk_id"]: c for c in ranked}
    citations: list[CitationItem] = []
    # Phase 2 bugfix P1-1: deduplicate citations by chunk_id so the
    # frontend never receives duplicate keys and the citations table
    # never holds duplicate chunk_id rows for a single message. The
    # first occurrence wins (highest confidence is usually first).
    seen_chunk_ids: set = set()
    for cite in result.get("citations", []):
        chunk_id = cite.get("chunk_id")
        if chunk_id is None:
            continue
        if chunk_id in seen_chunk_ids:
            continue
        chunk = chunk_map.get(chunk_id)
        if chunk is None:
            continue
        seen_chunk_ids.add(chunk_id)
        page_no = chunk.get("page_no")
        quote_text = cite.get("quote_text", "")
        confidence = cite.get("confidence", 0.0)
        material_name = chunk.get("filename", "")
        if page_no is not None:
            display_label = f"{material_name} · 第 {page_no} 页"
        else:
            display_label = material_name
        citations.append(
            CitationItem(
                chunk_id=cite["chunk_id"],
                material_name=material_name,
                page_no=page_no,
                quote_text=quote_text,
                confidence=confidence,
                display_label=display_label,
            )
        )
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

    retrieved_chunks = [
        RetrievedChunkItem(
            chunk_id=c["chunk_id"],
            score=c.get("score", 0),
            title=c.get("title"),
            page_no=c.get("page_no"),
            snippet=(c.get("text", "") or "")[:80],
            is_cited=any(ci.chunk_id == c["chunk_id"] for ci in citations),
        )
        for c in ranked
    ]

    if _should_persist_steps("success"):
        _safe_add_step(
            db, run_id=run_id, step_name="validate", step_index=2,
            input_data={"retrieved_chunk_count": len(ranked)},
            output_data={"citation_count": len(citations)},
            duration_ms=0,
        )

    total_duration = int((time.monotonic() - run_started_at) * 1000)
    _safe_finish_run(
        db, run_id=run_id, status="success",
        output_summary={
            "answer": _summarise(result.get("answer", ""), 200),
            "citation_count": len(citations),
        },
        duration_ms=total_duration,
    )

    response = ChatResponse(
        message_id=assistant_msg.id,
        answer=result.get("answer", ""),
        citations=citations,
        not_found=result.get("not_found", False),
        follow_up_questions=result.get("follow_up_questions", []),
        agent_run_id=run_id,
        reliability_level=result.get("reliability_level", "medium"),
        retrieved_chunks=retrieved_chunks,
    )

    yield {
        "event": "step_done",
        "step": "citation",
        "message": f"生成 {len(citations)} 个引用",
        "summary": {"citation_count": len(citations)},
    }
    yield {"event": "final", "data": response.model_dump(mode="json")}
