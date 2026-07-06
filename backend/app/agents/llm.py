"""LLM adapter layer.

Provides a single ``call_llm`` entry point used by all agents. Supports
two providers:

- ``mock``: returns deterministic structured JSON per ``agent_type``,
  so the full agent pipeline can be demoed without an API key.
- ``real``: calls an OpenAI-compatible API via httpx, parsing
  ``choices[0].message.content`` as JSON.

``call_llm`` implements a three-layer fallback so the platform stays
demoable even when the real provider is unavailable:

1. ``user_config``: a per-user OpenAI-compatible config supplied by the
   caller. If it fails, fall through to the system provider.
2. System ``real`` provider (``LLM_PROVIDER=real``): calls the API via
   :func:`_real_response`. On any exception, fall back to mock.
3. ``mock`` provider (``LLM_PROVIDER=mock``, the default): returns the
   deterministic payload for ``agent_type``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    agent_type: str,
    schema: dict | None = None,
    user_config: dict | None = None,
) -> dict:
    """Call the LLM and return a parsed JSON dict.

    Parameters
    ----------
    prompt:
        The fully-rendered prompt string to send to the model.
    agent_type:
        Which agent is calling. One of: ``course_qa``, ``outline``,
        ``planner``, ``task_decompose``, ``multi_course_schedule``,
        ``quiz_generate``, ``citation_verify``.
    schema:
        Optional JSON-schema-like dict describing required fields. Used
        by the real provider for response shaping; the mock provider
        ignores it and returns its own structurally-valid payload.
    user_config:
        Optional per-user OpenAI-compatible config. When supplied, the
        real provider is called with these credentials regardless of
        ``LLM_PROVIDER``. On any failure, the call falls back to the
        mock provider so the demo never breaks.

    Returns
    -------
    dict
        Parsed JSON response matching the agent's schema.

    Notes
    -----
    Three-layer fallback: ``user_config`` > system real provider > mock.
    Real-path failures (timeouts, HTTP errors, invalid JSON) are logged
    and swallowed so callers always receive a structurally-valid dict.
    """
    # 1. Prefer the per-user config when supplied.
    if user_config is not None:
        try:
            return _real_response(prompt, agent_type, schema, user_config)
        except Exception as exc:  # noqa: BLE001 - demo must stay up
            logger.warning(
                "User LLM config failed, falling back to mock: %s", exc
            )
            return _mock_response(agent_type)

    # 2. Otherwise defer to the system provider setting.
    provider = (settings.LLM_PROVIDER or "mock").lower()
    if provider == "real":
        try:
            return _real_response(prompt, agent_type, schema, None)
        except Exception as exc:  # noqa: BLE001 - demo must stay up
            logger.warning(
                "System real LLM failed, falling back to mock: %s", exc
            )
            return _mock_response(agent_type)

    # 3. Mock provider (default, or unknown provider) keeps the demo alive.
    return _mock_response(agent_type)


def _mock_response(agent_type: str) -> dict[str, Any]:
    """Return a deterministic, structurally-valid payload for ``agent_type``."""
    builder = _MOCK_BUILDERS.get(agent_type)
    if builder is None:
        # Unknown agent types get a minimal generic envelope so callers
        # still receive valid JSON.
        return {"agent_type": agent_type, "result": {}}
    return builder()


def _mock_course_qa() -> dict[str, Any]:
    return {
        "answer": (
            "梯度下降是一种迭代优化算法，通过沿损失函数梯度反方向更新参数，"
            "逐步逼近损失最小值。"
        ),
        "key_points": [
            "沿负梯度方向更新参数",
            "学习率决定步长",
            "可收敛到局部最优",
        ],
        "citations": [
            {
                "chunk_id": "chunk_1",
                "quote_text": "梯度下降沿负梯度方向迭代更新参数。",
                "reason": "该片段直接定义了梯度下降的核心思想。",
                "confidence": 0.92,
            }
        ],
        "not_found": False,
        "follow_up_questions": [
            "学习率过大或过小会带来什么问题？",
            "随机梯度下降与批量梯度下降有何区别？",
        ],
    }


def _mock_outline() -> dict[str, Any]:
    return {
        "knowledge_points": [
            {
                "title": "梯度下降基本原理",
                "summary": "通过负梯度方向迭代更新参数以最小化损失。",
                "importance": 5,
                "source_chunk_ids": ["chunk_1", "chunk_2"],
                "exam_style": "简答题/计算题",
                "review_action": "重读 chunk_1 并手推一次更新公式。",
            },
            {
                "title": "学习率的影响",
                "summary": "学习率过大发散，过小收敛慢。",
                "importance": 4,
                "source_chunk_ids": ["chunk_3"],
                "exam_style": "选择题/简答题",
                "review_action": "做两道学习率调整的练习题。",
            },
        ]
    }


def _mock_planner() -> dict[str, Any]:
    return {
        "goal_title": "两周内复习完《机器学习》前五章",
        "deadline": "2026-07-20",
        "daily_minutes": 120,
        "tasks": [
            {
                "course_name": "机器学习",
                "title": "复习第一章 绪论",
                "task_type": "review",
                "estimate_minutes": 90,
                "priority": 5,
                "acceptance": "能口述机器学习三大流派并举例。",
            },
            {
                "course_name": "机器学习",
                "title": "完成第二章习题",
                "task_type": "practice",
                "estimate_minutes": 60,
                "priority": 4,
                "acceptance": "习题正确率 ≥ 80%。",
            },
        ],
    }


def _mock_task_decompose() -> dict[str, Any]:
    return {
        "parent_task": "复习第一章 绪论",
        "subtasks": [
            {
                "title": "阅读 1.1-1.3 节",
                "task_type": "learn",
                "estimate_minutes": 40,
                "priority": 5,
                "acceptance": "能复述每节核心概念。",
                "depends_on": [],
            },
            {
                "title": "整理思维导图",
                "task_type": "review",
                "estimate_minutes": 30,
                "priority": 3,
                "acceptance": "导图覆盖全部小节标题。",
                "depends_on": ["阅读 1.1-1.3 节"],
            },
        ],
    }


def _mock_multi_course_schedule() -> dict[str, Any]:
    return {
        "schedule": [
            {
                "date": "2026-07-07",
                "course_name": "机器学习",
                "title": "复习绪论",
                "task_type": "review",
                "estimate_minutes": 60,
                "priority": 5,
                "acceptance": "能口述三大流派。",
            },
            {
                "date": "2026-07-07",
                "course_name": "数据结构",
                "title": "练习链表题",
                "task_type": "practice",
                "estimate_minutes": 60,
                "priority": 4,
                "acceptance": "完成 5 道链表题。",
            },
        ],
        "total_days": 14,
        "total_minutes": 1680,
    }


def _mock_quiz_generate() -> dict[str, Any]:
    return {
        "questions": [
            {
                "question_type": "single_choice",
                "difficulty": 3,
                "stem": "梯度下降更新参数的方向是？",
                "options": [
                    "正梯度方向",
                    "负梯度方向",
                    "随机方向",
                    "零向量方向",
                ],
                "answer": "B",
                "explanation": "沿负梯度方向更新可使损失下降。",
                "knowledge_point_ids": ["kp_1"],
                "source_chunk_ids": ["chunk_1"],
            },
            {
                "question_type": "short_answer",
                "difficulty": 4,
                "stem": "简述学习率过大可能带来的问题。",
                "options": [],
                "answer": "学习率过大会导致参数更新步长过大，可能越过最优点甚至发散。",
                "explanation": "步长过大时损失不单调下降，易震荡或发散。",
                "knowledge_point_ids": ["kp_2"],
                "source_chunk_ids": ["chunk_3"],
            },
        ]
    }


def _mock_citation_verify() -> dict[str, Any]:
    return {
        "verified": [
            {
                "chunk_id": "chunk_1",
                "valid": True,
                "quote_match": True,
                "supporting": True,
                "confidence": 0.9,
                "note": "引用文本与原文一致，且支撑回答。",
            }
        ],
        "issues": [],
        "overall_pass": True,
    }


_MOCK_BUILDERS = {
    "course_qa": _mock_course_qa,
    "outline": _mock_outline,
    "planner": _mock_planner,
    "task_decompose": _mock_task_decompose,
    "multi_course_schedule": _mock_multi_course_schedule,
    "quiz_generate": _mock_quiz_generate,
    "citation_verify": _mock_citation_verify,
}


def _real_response(
    prompt: str,
    agent_type: str,
    schema: dict | None,
    user_config: dict | None,
) -> dict[str, Any]:
    """Call an OpenAI-compatible ``/chat/completions`` API via httpx.

    The request body always carries ``response_format={"type":
    "json_object"}`` so the model returns parseable JSON. If the server
    rejects this field with a 400, the call is retried once without it
    to stay compatible with providers that do not support JSON mode.

    Parameters
    ----------
    prompt:
        The fully-rendered prompt string to send to the model.
    agent_type:
        Which agent is calling. Currently unused by the real path but
        kept for symmetry with :func:`call_llm` and future telemetry.
    schema:
        Optional JSON-schema-like dict. Reserved for response shaping;
        not yet enforced here.
    user_config:
        Optional per-user config dict (``base_url``, ``model``,
        ``api_key``, ``temperature``, ``max_tokens``,
        ``timeout_seconds``). When ``None``, falls back to the system
        ``settings`` values.

    Returns
    -------
    dict
        The parsed ``choices[0].message.content`` JSON.

    Raises
    ------
    Exception
        Any httpx/JSON error propagates to :func:`call_llm`, which is
        responsible for falling back to the mock provider.
    """
    if user_config is not None:
        base_url = user_config["base_url"]
        model = user_config["model"]
        api_key = user_config["api_key"]
        temperature = user_config.get("temperature", settings.LLM_TEMPERATURE)
        max_tokens = user_config.get("max_tokens", settings.LLM_MAX_TOKENS)
        timeout = user_config.get("timeout_seconds", settings.LLM_TIMEOUT_SECONDS)
    else:
        base_url = settings.LLM_BASE_URL
        model = settings.LLM_MODEL
        api_key = settings.LLM_API_KEY
        temperature = settings.LLM_TEMPERATURE
        max_tokens = settings.LLM_MAX_TOKENS
        timeout = settings.LLM_TIMEOUT_SECONDS

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=timeout) as client:
        # First attempt asks for JSON-mode output.
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code == 400:
            # Some OpenAI-compatible backends reject response_format;
            # retry once without it so we still get a usable answer.
            body.pop("response_format", None)
            resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


__all__ = ["call_llm"]
