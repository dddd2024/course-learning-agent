"""PlannerAgent — decomposes a learning goal into stage tasks.

The agent:
1. Loads the ``planner`` prompt template and fills the ``{goal}`` /
   ``{courses}`` / ``{deadline}`` / ``{daily_minutes}`` placeholders.
2. Calls ``call_llm`` with ``agent_type="planner"`` to get a structured
   JSON response with a ``goal_title`` and a ``tasks`` list.
3. Reconciles each task's ``course_name`` against the user's actual
   course list (the mock LLM returns placeholder strings like
   ``"机器学习"``; the real LLM may return names that need validating),
   falling back to the first available course when no match is found.
4. Normalises ``deadline`` / ``daily_minutes`` to the user's input so
   the output is ready for persistence (the mock returns fixed values
   that may not match what the user requested).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agents.llm import call_llm
from app.agents.prompt_loader import load_prompt

_REQUIRED_TASK_FIELDS = (
    "course_name",
    "title",
    "task_type",
    "estimate_minutes",
    "priority",
    "acceptance",
)


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
        db: SQLAlchemy session (reserved for future agent-run logging).
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

    output = call_llm(
        prompt, agent_type="planner", user_config=user_config
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
    return output


__all__ = ["generate"]
