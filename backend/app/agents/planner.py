"""PlannerAgent — decomposes a learning goal into stage tasks.

The agent:
1. Loads the ``planner`` prompt template and fills the ``{goal}`` /
   ``{courses}`` / ``{deadline}`` / ``{daily_minutes}`` placeholders.
2. Calls ``call_llm_with_meta`` with ``agent_type="planner"`` to get a
   structured JSON response with a ``goal_title`` and a ``tasks`` list.
3. Reconciles each task's ``course_name`` against the user's actual
   course list (the mock LLM returns placeholder strings like
   ``"机器学习"``; the real LLM may return names that need validating),
   falling back to the first available course when no match is found.
4. Normalises ``deadline`` / ``daily_minutes`` to the user's input so
   the output is ready for persistence (the mock returns fixed values
   that may not match what the user requested).
5. Records an ``AgentAudit`` run (``create_run`` -> ``add_step`` ->
   ``finalize_run``); audit failures are swallowed so they never break
   the main flow.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agents.audit import AgentAudit
from app.agents.llm import call_llm_with_meta
from app.agents.prompt_loader import load_prompt
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "planner_v1"


def _format_courses(courses: list[str]) -> str:
    """Render the course list into a readable prompt section."""
    if not courses:
        return "（无关联课程）"
    return "、".join(courses)


def _reconcile_course_name(raw_name: str, valid_names: list[str]) -> str:
    """Match the LLM-returned course_name to an actual course name.

    Falls back to the first valid name when no match is found (e.g. the
    mock LLM returns ``"机器学习"`` while the user passed
    ``["操作系统"]``).
    """
    if raw_name and raw_name in valid_names:
        return raw_name
    if valid_names:
        return valid_names[0]
    return raw_name or ""


def _coerce_int(value: Any, default: int) -> int:
    """Best-effort int conversion with a fallback for malformed LLM output."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def generate(
    db: Session,
    user_id: int,
    goal: str,
    courses: list[str],
    deadline: date,
    daily_minutes: int,
    user_config: dict | None = None,
) -> dict[str, Any]:
    """Decompose ``goal`` into stage tasks ready for persistence.

    Args:
        db: SQLAlchemy session (used for agent-run audit logging).
        user_id: The user the plan is being built for.
        goal: The user's free-text learning goal.
        courses: Display names of the user's actual courses. Each
            task's ``course_name`` is reconciled to one of these.
        deadline: The user's chosen deadline.
        daily_minutes: The user's daily study budget.
        user_config: Optional per-user LLM config dict. When supplied,
            it is forwarded to :func:`call_llm` so the call uses the
            user's enabled provider config.

    Returns:
        A dict with ``goal_title`` / ``deadline`` / ``daily_minutes``
        and a ``tasks`` list, each task carrying ``course_name``,
        ``title``, ``task_type``, ``estimate_minutes``, ``priority``,
        ``acceptance``. The output is ready for direct persistence.
    """
    template = load_prompt("planner")
    prompt = template.format(
        goal=goal,
        courses=_format_courses(courses),
        deadline=str(deadline),
        daily_minutes=daily_minutes,
    )

    # Determine provider/model_name before LLM call (best guess).
    if user_config:
        _provider = "user"
        _model = user_config.get("model", "")
    else:
        _provider = "real" if settings.LLM_PROVIDER == "real" else "mock"
        _model = settings.LLM_MODEL

    run_started_at = time.monotonic()
    run_id: int | None = None
    try:
        run = AgentAudit.create_run(
            db,
            user_id=user_id,
            run_type="planner",
            input_summary={
                "goal": goal,
                "courses": courses,
                "deadline": str(deadline),
                "daily_minutes": daily_minutes,
            },
            prompt_version=_PROMPT_VERSION,
            model_name=_model,
            provider=_provider,
        )
        run_id = run.id
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.create_run(planner) failed: %s", exc)

    generate_started = time.monotonic()
    try:
        output, meta = call_llm_with_meta(
            prompt, agent_type="planner", user_config=user_config
        )
        # Update audit run with actual provider/model_name from meta
        AgentAudit.update_run_meta(
            db, run_id,
            model_name=meta.get("model_name"),
            provider=meta.get("provider"),
            meta=meta,
        )
    except Exception as exc:
        generate_duration = int((time.monotonic() - generate_started) * 1000)
        _safe_finalize_run(
            db, run_id=run_id,
            error=str(exc),
            duration_ms=generate_duration,
        )
        raise
    generate_duration = int((time.monotonic() - generate_started) * 1000)

    _safe_add_step(
        db, run_id=run_id,
        step_name="generate", step_index=0,
        input_data={"prompt_version": _PROMPT_VERSION},
        output_data={"task_count": len(output.get("tasks", []))},
        duration_ms=generate_duration,
    )

    # Normalise scalar fields to the user's input so the persisted goal
    # matches what the user actually requested (the mock LLM returns
    # fixed values that may differ from the input).
    output["goal_title"] = output.get("goal_title") or goal
    output["deadline"] = str(deadline)
    output["daily_minutes"] = daily_minutes

    valid_names = list(courses)
    normalised_tasks: list[dict[str, Any]] = []
    for raw_task in output.get("tasks", []) or []:
        normalised_tasks.append(
            {
                "course_name": _reconcile_course_name(
                    raw_task.get("course_name", ""), valid_names
                ),
                "title": raw_task.get("title", ""),
                "task_type": raw_task.get("task_type", "review"),
                "estimate_minutes": _coerce_int(
                    raw_task.get("estimate_minutes", 60), 60
                ),
                "priority": _coerce_int(raw_task.get("priority", 3), 3),
                "acceptance": raw_task.get("acceptance", ""),
            }
        )
    output["tasks"] = normalised_tasks

    _safe_finalize_run(
        db, run_id=run_id,
        fallback_used=bool(meta.get("fallback_used", False)),
        output_summary={
            "task_count": len(normalised_tasks),
            "meta_observed": meta.get("meta_observed") is True,
        },
        duration_ms=int((time.monotonic() - run_started_at) * 1000),
    )

    return output


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


def _safe_finalize_run(
    db: Session,
    run_id: int | None,
    error: str | None = None,
    fallback_used: bool = False,
    evidence_status: str | None = None,
    output_summary=None,
    duration_ms: int | None = None,
) -> None:
    """Finalize an audit run, swallowing any error so the main flow runs on."""
    if run_id is None:
        return
    try:
        AgentAudit.finalize_run(
            db,
            run_id=run_id,
            error=error,
            fallback_used=fallback_used,
            evidence_status=evidence_status,
            output_summary=output_summary,
            duration_ms=duration_ms,
        )
    except Exception as exc:  # pragma: no cover - audit must not break flow
        logger.warning("AgentAudit.finalize_run(planner) failed: %s", exc)


__all__ = ["generate"]
