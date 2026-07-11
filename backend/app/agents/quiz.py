"""QuizAgent — generates quiz questions from a course's knowledge points.

The agent:
1. Loads the ``quiz_generate`` prompt template and fills the
   ``{course_name}`` / ``{question_count}`` / ``{retrieved_chunks}`` /
   ``{knowledge_points}`` / ``{question_types}`` placeholders.
2. Calls ``call_llm`` with ``agent_type="quiz_generate"`` to get a
   structured JSON response with a ``questions`` list.
3. Validates the response shape via ``_validate_schema``.
4. Normalises each question:
   - ``question_type`` is mapped to ``choice`` / ``true_false`` /
     ``short_answer``.
   - ``stem`` is renamed to ``question_text``.
   - ``options`` are prefixed with letters (``A. `` / ``B. `` ...).
   - ``knowledge_point_ids`` (mock placeholder strings like ``"kp_1"``)
     are reconciled to actual ``KnowledgePoint.id`` values.
5. Records an ``AgentAudit`` run (``create_run`` -> ``add_step`` ->
   ``finish_run``); audit failures are swallowed so they never break
   the main flow.
6. Returns ``{title, items}`` ready for persistence.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.agents.llm import call_llm_with_meta
from app.agents.prompt_loader import load_prompt
from app.core.config import settings
from app.models.knowledge_point import KnowledgePoint

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "quiz_generate_v1"

_REQUIRED_QUESTION_FIELDS = (
    "question_type",
    "stem",
    "answer",
)

# Map the LLM's question_type values to the persisted enum.
_TYPE_MAP = {
    "single_choice": "choice",
    "multiple_choice": "multiple_choice",
    "choice": "choice",
    "true_false": "true_false",
    "short_answer": "short_answer",
}


def _format_knowledge_points(knowledge_points: list[KnowledgePoint]) -> str:
    """Render knowledge points into a readable prompt section."""
    if not knowledge_points:
        return "（无指定知识点）"
    lines = []
    for i, kp in enumerate(knowledge_points, start=1):
        lines.append(f"[知识点{i}] kp_id=kp_{i} 标题={kp.title}")
        if kp.summary:
            lines.append(f"  摘要：{kp.summary}")
    return "\n".join(lines)


def _format_question_types() -> str:
    """Return the question-type section for the prompt."""
    return "选择题、判断题、简答题，难度分布合理。"


def _normalise_question_type(raw: str) -> str:
    """Map the LLM-returned question_type to the persisted enum."""
    if not raw:
        return "short_answer"
    return _TYPE_MAP.get(raw, raw)


def _normalise_rubric(raw: Any) -> list[dict[str, Any]]:
    """Keep only machine-checkable criteria supplied for short answers."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for criterion in raw[:6]:
        if not isinstance(criterion, dict):
            continue
        keywords = [str(value).strip() for value in criterion.get("keywords", []) if str(value).strip()]
        if keywords:
            result.append({"criterion": str(criterion.get("criterion") or "关键要点"), "keywords": keywords[:5]})
    return result


def _prefix_options(options: list[str]) -> list[dict[str, str]]:
    """Add ``A. `` / ``B. `` prefixes to options if not already present."""
    if not options:
        return []
    letters = "ABCDEFGH"
    result: list[dict[str, str]] = []
    for i, opt in enumerate(options):
        if not isinstance(opt, str):
            opt = str(opt)
        # Skip prefixing if the option already looks prefixed.
        if len(opt) >= 2 and opt[1] == "." and opt[0].isalpha():
            result.append({"label": opt[0].upper(), "text": opt[2:].strip(), "value": opt[0].upper()})
            continue
        prefix = letters[i] if i < len(letters) else str(i)
        result.append({"label": prefix, "text": opt, "value": prefix})
    return result


def _map_knowledge_point_id(
    raw_ids: list,
    question_index: int,
    knowledge_points: list[KnowledgePoint],
) -> int | None:
    """Map the LLM-returned kp id placeholder to an actual KP id.

    The mock returns strings like ``"kp_1"``; we parse the trailing
    number as a 1-based index into ``knowledge_points``. Falls back to
    rotating by question index when parsing fails, and to ``None`` when
    no knowledge points are available.
    """
    if not knowledge_points:
        return None
    for rid in raw_ids or []:
        if isinstance(rid, str) and rid.startswith("kp_"):
            try:
                idx = int(rid[3:]) - 1
                if 0 <= idx < len(knowledge_points):
                    return knowledge_points[idx].id
            except ValueError:
                continue
        if isinstance(rid, int):
            for kp in knowledge_points:
                if kp.id == rid:
                    return kp.id
    # Fallback: rotate by question index so every question gets a KP.
    return knowledge_points[question_index % len(knowledge_points)].id


def _validate_schema(output: dict) -> None:
    """Ensure the LLM output has the expected shape.

    Raises ``ValueError`` when required top-level or per-question fields
    are missing so the caller can surface a clear error.
    """
    if not isinstance(output, dict):
        raise ValueError("LLM output must be a dict")
    questions = output.get("questions")
    if not isinstance(questions, list):
        raise ValueError("LLM output missing 'questions' list")
    if not questions:
        raise ValueError("LLM returned no questions")
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f"Question {i} is not a dict")
        for field in _REQUIRED_QUESTION_FIELDS:
            if field not in q:
                raise ValueError(f"Question {i} missing field '{field}'")


def generate_quiz(
    db: Session,
    user_id: int,
    course_id: int,
    knowledge_points: list[KnowledgePoint],
    course_name: str,
    question_count: int = 5,
    user_config: dict | None = None,
) -> dict[str, Any]:
    """Generate a quiz for a course's knowledge points.

    Args:
        db: SQLAlchemy session.
        user_id: The user the quiz is being generated for (for audit).
        course_id: The course the quiz belongs to.
        knowledge_points: List of ``KnowledgePoint`` ORM rows to tie
            questions to. Pass an empty list to get an empty result.
        course_name: Display name of the course (used in the title /
            prompt).
        question_count: Hint for the number of questions. The mock LLM
            ignores this; the real LLM will honour it.
        user_config: Optional per-user LLM config dict. When supplied,
            it is forwarded to :func:`call_llm` so the call uses the
            user's enabled provider config.

    Returns:
        A dict with ``title`` and ``items`` (each item carrying
        ``question_type``, ``question_text``, ``options``, ``answer``,
        ``explanation``, ``knowledge_point_id``).
    """
    if not knowledge_points:
        return {
            "title": f"{course_name} 测验 "
            f"({datetime.now().strftime('%m-%d %H:%M')})",
            "items": [],
        }

    template = load_prompt("quiz_generate")
    prompt = template.format(
        course_name=course_name,
        question_count=question_count,
        retrieved_chunks=_format_evidence(db, knowledge_points),
        knowledge_points=_format_knowledge_points(knowledge_points),
        question_types=_format_question_types(),
    )

    run_started_at = time.monotonic()
    run_id: int | None = None
    # Determine provider/model_name before LLM call (best guess).
    if user_config:
        _provider = "user"
        _model = user_config.get("model", "")
    else:
        _provider = "real" if settings.LLM_PROVIDER == "real" else "mock"
        _model = settings.LLM_MODEL
    try:
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="quiz",
            input_summary={
                "course_id": course_id,
                "course_name": course_name,
                "knowledge_point_count": len(knowledge_points),
                "question_count": question_count,
            },
            prompt_version=_PROMPT_VERSION,
            model_name=_model,
            provider=_provider,
        )
        run_id = run.id
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.create_run(quiz) failed: %s", exc)

    generate_started = time.monotonic()
    try:
        output, meta = call_llm_with_meta(
            prompt,
            agent_type="quiz_generate",
            user_config=user_config,
        )
        # Update audit run with actual provider/model_name from meta
        AgentAudit.update_run_meta(
            db, run_id,
            model_name=meta.get("model_name"),
            provider=meta.get("provider"),
            meta=meta,
        )
        _validate_schema(output)
    except Exception:
        _safe_finish_run(
            db,
            run_id=run_id,
            status="failed",
            started_at=run_started_at,
        )
        raise
    generate_duration = int((time.monotonic() - generate_started) * 1000)

    _safe_add_step(
        db,
        run_id=run_id,
        step_name="generate",
        step_index=0,
        input_data={"prompt_version": _PROMPT_VERSION},
        output_data={"question_count": len(output.get("questions", []))},
        duration_ms=generate_duration,
    )

    items: list[dict[str, Any]] = []
    for i, q in enumerate(output.get("questions", [])):
        items.append(
            {
                "question_type": _normalise_question_type(
                    q.get("question_type", "")
                ),
                "question_text": q.get("stem", ""),
                "options": _prefix_options(q.get("options", [])),
                "answer": str(q.get("answer", "")),
                "rubric": _normalise_rubric(q.get("rubric")),
                "explanation": q.get("explanation", ""),
                "difficulty": q.get("difficulty"),
                "source_evidence_ids": _valid_evidence_ids(
                    db, course_id, q.get("source_chunk_ids", []), knowledge_points
                ),
                "knowledge_point_id": _map_knowledge_point_id(
                    q.get("knowledge_point_ids", []), i, knowledge_points
                ),
                "order_index": i,
            }
        )

    _safe_finish_run(
        db,
        run_id=run_id,
        status="success",
        output_summary={"item_count": len(items)},
        started_at=run_started_at,
    )

    # Build a unique, descriptive title. Prefer the LLM-returned title
    # (which summarises the knowledge-point topics); otherwise fall back
    # to a course-name + timestamp title so repeated quizzes for the
    # same course remain distinguishable.
    timestamp = datetime.now().strftime("%m-%d %H:%M")
    llm_title = output.get("title")
    if isinstance(llm_title, str) and llm_title.strip():
        title = f"{course_name} - {llm_title.strip()} ({timestamp})"
    else:
        title = f"{course_name} 测验 ({timestamp})"

    return {
        "title": title,
        "items": items,
    }


def _valid_evidence_ids(db: Session, course_id: int, raw_ids: list, points: list[KnowledgePoint]) -> list[int]:
    """Accept only active chunks in this course, never model-invented IDs."""
    import json
    from app.models.material_chunk import MaterialChunk
    valid = {r[0] for r in db.query(MaterialChunk.id).filter(
        MaterialChunk.course_id == course_id, MaterialChunk.is_active == 1
    )}
    selected = [int(x) for x in raw_ids if str(x).isdigit() and int(x) in valid]
    if selected:
        return selected[:5]
    for point in points:
        try:
            selected = [int(x) for x in json.loads(point.source_chunk_ids or "[]") if int(x) in valid]
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if selected:
            return selected[:5]
    return []


def _format_evidence(db: Session, points: list[KnowledgePoint]) -> str:
    import json
    from app.models.material_chunk import MaterialChunk
    ids: list[int] = []
    for point in points:
        try:
            ids.extend(int(x) for x in json.loads(point.source_chunk_ids or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    rows = db.query(MaterialChunk).filter(
        MaterialChunk.id.in_(ids), MaterialChunk.is_active == 1
    ).limit(20).all() if ids else []
    return "\n".join(f"[evidence_id={r.id} page={r.page_no}] {r.text[:500]}" for r in rows)


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
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.add_step(%s) failed: %s", step_name, exc)


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
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.finish_run(quiz) failed: %s", exc)


__all__ = ["generate_quiz"]
