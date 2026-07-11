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


def _build_conversation_context(db: Session, conversation_id: int) -> str:
    """Build a bounded, role-labelled context for resolution and retrieval.

    Historical assistant text is deliberately labelled as unverified context;
    the course chunks retrieved afterwards remain the only factual source.
    """
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(6)
        .all()
    )
    return "\n".join(
        f"{'学生' if message.role == 'user' else '助手（未验证上下文）'}："
        f"{_summarise(message.content or '', 600)}"
        for message in reversed(messages)
        if message.content
    )


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
    *,
    course_id: int | None = None,
    agent_run_id: int | None = None,
) -> None:
    """Persist an agent failure to agent_error_logs AND error_logs (best-effort).

    The legacy ``AgentErrorLog`` row is kept for the Agent audit page.
    A new ``ErrorLog(category=agent)`` row is also written so the failure
    shows up in the user-facing log center.
    """
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

    # Also write a general ErrorLog so the failure appears in the log center.
    try:
        from app.services.error_logger import log_error

        step_label = {
            "retrieve": "检索",
            "generate": "生成",
            "validate": "验证",
            "persist": "持久化",
        }.get(step, step)

        log_error(
            db,
            user_id,
            category="agent",
            level="error",
            title="Agent 执行失败",
            message=f"{step_label}步骤失败：{exc.__class__.__name__}: {exc}",
            technical_detail=tb[:1000],
            course_id=course_id,
            agent_run_id=agent_run_id,
        )
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

    # Preserve recent turns before the current question is persisted. The
    # bounded context is used for pronoun resolution in both retrieval and
    # generation, never as an evidence source.
    conversation_context = _build_conversation_context(db, conversation.id)

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
        retrieval_query = question
        if conversation_context:
            retrieval_query = f"{question}\n\n近期上下文：\n{conversation_context}"
        candidates = keyword_search(db, course_id, retrieval_query, top_k=12)
        ranked = rerank(retrieval_query, candidates, top_k=6)
    except Exception as exc:
        _log_error(db, current_user.id, conversation_id, "retrieve",
                   provider, model_name, config_id, exc,
                   course_id=course_id, agent_run_id=run_id)
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
                "query": _summarise(retrieval_query, 800),
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

    # T06: when no chunks were retrieved, short-circuit to a clear
    # "no materials" answer instead of calling the LLM (which would
    # return a canned mock answer unrelated to the course and mislead
    # the user into thinking the course has content).
    if not ranked:
        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="未检索到与该问题相关的课程资料，请先上传并解析材料后再提问。",
            answer_json=json.dumps(
                {
                    "answer": "未检索到与该问题相关的课程资料，请先上传并解析材料后再提问。",
                    "not_found": True,
                    "citations": [],
                    "follow_up_questions": [],
                    "provider": "mock",
                    "fallback_used": False,
                    "fallback_reason": None,
                },
                ensure_ascii=False,
            ),
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)
        _safe_finish_run(
            db,
            run_id=run_id,
            status="success",
            output_summary={"not_found": True, "citation_count": 0},
            duration_ms=int((time.monotonic() - run_started_at) * 1000),
        )
        yield {
            "event": "final",
            "data": ChatResponse(
                message_id=assistant_msg.id,
                answer="未检索到与该问题相关的课程资料，请先上传并解析材料后再提问。",
                citations=[],
                not_found=True,
                follow_up_questions=[],
                agent_run_id=run_id,
                reliability_level="failed",
                retrieved_chunks=[],
                provider="mock",
                fallback_used=False,
                fallback_reason=None,
            ).model_dump(mode="json"),
        }
        return

    # 3. Generate. Include a bounded, role-labelled history only to resolve
    # references such as “它” or “前者”; retrieval evidence remains primary.
    yield {"event": "step_started", "step": "generate", "message": "正在调用模型"}
    course = db.query(Course).filter(Course.id == course_id).first()
    course_name = course.name if course else ""
    generate_started = time.monotonic()
    try:
        result = answer_question(
            db, course_id, question, ranked, course_name,
            user_config=user_config, conversation_context=conversation_context,
        )
    except Exception as exc:
        generate_duration = int((time.monotonic() - generate_started) * 1000)
        _log_error(db, current_user.id, conversation_id, "generate",
                   provider, model_name, config_id, exc,
                   course_id=course_id, agent_run_id=run_id)
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
        # A citation quote must be verifiable against the retrieved source;
        # do not persist model-invented quotes merely because the chunk id is
        # valid.
        if not quote_text or quote_text not in (chunk.get("text") or ""):
            continue
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
                claim_text=cite.get("claim_text", ""),
                support_status=cite.get("support_status", "weak"),
                verification_reason=cite.get("verification_reason", ""),
                verifier_version=cite.get("verifier_version", ""),
            )
        )
        db.add(
            Citation(
                message_id=assistant_msg.id,
                chunk_id=cite["chunk_id"],
                quote_text=quote_text,
                claim_text=cite.get("claim_text", ""),
                support_status=cite.get("support_status", "weak"),
                verification_reason=cite.get("verification_reason", ""),
                verifier_version=cite.get("verifier_version", ""),
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
        # T05: surface provider/fallback state on the response.
        provider=result.get("provider", "mock"),
        fallback_used=result.get("fallback_used", False),
        fallback_reason=result.get("fallback_reason"),
    )

    yield {
        "event": "step_done",
        "step": "citation",
        "message": f"生成 {len(citations)} 个引用",
        "summary": {"citation_count": len(citations)},
    }
    yield {"event": "final", "data": response.model_dump(mode="json")}
