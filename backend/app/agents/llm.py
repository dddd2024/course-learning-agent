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
import re
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

    Thin wrapper around :func:`call_llm_with_meta` that discards the
    meta information. Kept for backward compatibility with callers that
    do not need provider/fallback visibility (T05).

    Returns
    -------
    dict
        Parsed JSON response matching the agent's schema.
    """
    result, _meta = call_llm_with_meta(prompt, agent_type, schema, user_config)
    return result


def call_llm_with_meta(
    prompt: str,
    agent_type: str,
    schema: dict | None = None,
    user_config: dict | None = None,
) -> tuple[dict, dict]:
    """Call the LLM and return ``(result, meta)``.

    ``meta`` is a dict with keys:
    - ``provider``: ``"real"`` or ``"mock"``
    - ``fallback_used``: True when a real call failed and we fell back to mock
    - ``fallback_reason``: short string explaining the failure (or ``None``)

    Three-layer fallback: ``user_config`` > system real provider > mock.
    Real-path failures (timeouts, HTTP errors, invalid JSON) are logged
    and swallowed so callers always receive a structurally-valid dict.
    """
    # 1. Prefer the per-user config when supplied.
    if user_config is not None:
        try:
            result = _real_response(prompt, agent_type, schema, user_config)
            return result, {
                "provider": "real",
                "fallback_used": False,
                "fallback_reason": None,
            }
        except Exception as exc:  # noqa: BLE001 - demo must stay up
            logger.warning(
                "User LLM config failed, falling back to mock: %s", exc
            )
            return _mock_response(agent_type, prompt), {
                "provider": "mock",
                "fallback_used": True,
                "fallback_reason": str(exc) or exc.__class__.__name__,
            }

    # 2. Otherwise defer to the system provider setting.
    provider = (settings.LLM_PROVIDER or "mock").lower()
    if provider == "real":
        try:
            result = _real_response(prompt, agent_type, schema, None)
            return result, {
                "provider": "real",
                "fallback_used": False,
                "fallback_reason": None,
            }
        except Exception as exc:  # noqa: BLE001 - demo must stay up
            logger.warning(
                "System real LLM failed, falling back to mock: %s", exc
            )
            return _mock_response(agent_type, prompt), {
                "provider": "mock",
                "fallback_used": True,
                "fallback_reason": str(exc) or exc.__class__.__name__,
            }

    # 3. Mock provider (default, or unknown provider) keeps the demo alive.
    return _mock_response(agent_type, prompt), {
        "provider": "mock",
        "fallback_used": False,
        "fallback_reason": None,
    }


def _mock_response(
    agent_type: str, prompt: str = ""
) -> dict[str, Any]:
    """Return a deterministic, structurally-valid payload for ``agent_type``."""
    builder = _MOCK_BUILDERS.get(agent_type)
    if builder is None:
        # Unknown agent types get a minimal generic envelope so callers
        # still receive valid JSON.
        return {"agent_type": agent_type, "result": {}}
    return builder(prompt)


def _mock_course_qa(prompt: str = "") -> dict[str, Any]:
    """Generate a context-aware mock answer from the prompt content.

    Parses the question and retrieved chunks from the prompt to produce
    a relevant answer instead of hardcoded "梯度下降" content. Falls back
    to a generic answer when the prompt structure is unexpected.
    """
    # Extract the user's question from the prompt.
    question = ""
    q_match = re.search(r"用户问题[:：]\s*(.+?)(?:\n|$)", prompt)
    if q_match:
        question = q_match.group(1).strip()

    # Extract chunk text from the prompt (same format as _mock_outline).
    chunk_pattern = re.compile(
        r"\[片段\d+\]\s*chunk_id=(\d+)[^\n]*\n(.+?)(?=\n\n|\Z)",
        re.DOTALL,
    )
    chunks = chunk_pattern.findall(prompt)

    if chunks:
        # Use the first chunk's text as the basis for the answer.
        first_cid, first_text = chunks[0]
        first_text = first_text.strip()
        # Build an answer from the first chunk content.
        answer = first_text[:200]
        if len(first_text) > 200:
            answer += "…"

        key_points: list[str] = []
        for cid, text in chunks[:3]:
            lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
            if lines:
                key_points.append(lines[0][:60])

        citations = [
            {
                "chunk_id": first_cid,
                "quote_text": first_text[:150],
                "reason": "该片段直接回答了用户的问题。",
                "confidence": 0.85,
            }
        ]
        follow_ups = [
            f"关于「{question[:20]}」还有哪些需要注意的地方？",
        ] if question else []
    else:
        # No chunks in prompt — return a minimal generic answer.
        answer = (
            f"根据课程资料，关于「{question or '该问题'}」的内容"
            "在现有资料中有相关描述，但未找到直接定义。"
        )
        key_points = []
        citations = []
        follow_ups = []

    return {
        "answer": answer,
        "key_points": key_points,
        "citations": citations,
        "not_found": False,
        "follow_up_questions": follow_ups,
    }


def _extract_title_from_chunk(chunk_text: str, index: int) -> str:
    """Extract a meaningful title from chunk text.

    Tries multiple strategies to find a good title:
    1. Lines matching chapter/section patterns (第X章, X.Y, §X, etc.)
       — chapter/section prefixes are stripped to get the concept name
    2. Short lines (< 30 chars) that look like headings
    3. First non-trivial line
    Skips lines that are course names, page numbers, dates, or boilerplate.
    """
    SKIP_PATTERNS = [
        "计算机网络", "操作系统", "数据结构", "数据库",
        "主要内容", "教学内容", "网络空间安全学院",
        "第", "页", "2024", "2025", "2026", "2027",
        "Forouzan", "Tanenbaum", "版权说明",
        # Figure/table/meta references from OCR extraction
        "标题", "图5-", "图6-", "图7-", "图8-", "图9-",
        "表5-", "表6-", "表7-", "表8-", "表9-",
    ]
    # Lines starting with figure/table/meta markers
    META_LINE_RE = re.compile(
        r"^(标题\d|图\d|表\d|第\d+行|第\d+图)"
    )
    SECTION_RE = re.compile(
        r"^(第[一二三四五六七八九十\d]+[章节]|"
        r"\d+[\.\-]\d+|"
        r"[一二三四五六七八九十]+、|"
        r"§\d+|"
        r"Chapter\s+\d+)"
    )
    # Pattern to strip chapter/section prefix from a title
    PREFIX_RE = re.compile(
        r"^(第[一二三四五六七八九十\d]+[章节]\s*|"
        r"\d+[\.\-]\d+(?:[\.\-]\d+)*\s*|"
        r"[一二三四五六七八九十]+、\s*|"
        r"§\d+\s*|"
        r"Chapter\s+\d+\s*)"
    )
    # Lines that are pure noise (IP addresses, MAC addresses, etc.)
    NOISE_LINE_RE = re.compile(r"^[\d\.\s:abcdefABCDEF-]+$")

    def _clean_title_line(line: str) -> str:
        """Strip prefix and noise from a title line."""
        # Remove chapter/section prefix
        cleaned = PREFIX_RE.sub("", line).strip()
        # Remove leading year numbers
        cleaned = re.sub(r"^\d{4}\s*", "", cleaned).strip()
        return cleaned

    lines = [l.strip() for l in chunk_text.strip().split("\n") if l.strip()]

    # Strategy 1: Find lines matching section/chapter patterns
    for line in lines:
        if SECTION_RE.match(line) and len(line) < 60:
            # Skip lines containing dates or meta info
            if any(s in line for s in SKIP_PATTERNS):
                continue
            if META_LINE_RE.match(line):
                continue
            # Strip the prefix to get the concept name
            cleaned = _clean_title_line(line)
            if cleaned and len(cleaned) >= 2:
                return cleaned[:60]

    # Strategy 2: Find short lines that look like headings
    for line in lines:
        if len(line) < 30 and not any(s in line for s in SKIP_PATTERNS):
            # Skip lines that are just numbers or symbols
            if re.match(r"^[\d\s\.\-]+$", line):
                continue
            if NOISE_LINE_RE.match(line):
                continue
            if META_LINE_RE.match(line):
                continue
            # Skip very short lines (< 4 chars) that are likely noise
            if len(line) < 4:
                continue
            return line[:60]

    # Strategy 3: First non-trivial line (skip course names and headers)
    for line in lines:
        if not any(line.startswith(s) for s in SKIP_PATTERNS):
            if NOISE_LINE_RE.match(line):
                continue
            if META_LINE_RE.match(line):
                continue
            if len(line) < 4:
                continue
            return line[:60]

    return f"知识点{index + 1}"


def _mock_outline(prompt: str = "") -> dict[str, Any]:
    """Generate knowledge points from the prompt's chunk content.

    Extracts chunk text from the prompt and uses _extract_title_from_chunk
    to find meaningful titles (section headings, short descriptive lines)
    instead of just taking the first line which is often a repeated page
    header like "计算机网络".
    """
    # Patterns for cleaning summary text
    SUMMARY_NOISE = re.compile(
        r"[□☐◆■►●○▪▫▶▷◇★☆▼▽▲△]"  # noise symbols
        r"|\d{4}年(?:\d+月)?(?:春|秋|夏|冬)?"  # dates with 年
        r"|\b\d{4}\b"  # standalone years
        r"|第\d+页|P\d+"  # page refs
        r"|\[Forouzan\]|\[Tanenbaum\]|\[谢\]"  # bib tags
        r"|网络空间安全学院"  # institution
    )

    def _clean_summary(text: str) -> str:
        cleaned = SUMMARY_NOISE.sub("", text)
        cleaned = re.sub(r"\n+", " ", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

    # Extract chunk text from the prompt.
    chunk_pattern = re.compile(
        r"\[片段\d+\]\s*chunk_id=\d+[^\n]*\n(.+?)(?=\n\n|\Z)",
        re.DOTALL,
    )
    chunks = chunk_pattern.findall(prompt)

    # Extract titles from the prompt header lines (format: "，标题：xxx")
    title_pattern = re.compile(r"标题：(.+?)(?:，|\n)")
    chunk_titles = title_pattern.findall(prompt)

    if not chunks:
        return {"knowledge_points": []}

    # Broad titles to skip when using DB chunk titles
    BROAD_DB_TITLES = {
        "计算机网络", "操作系统", "数据结构", "数据库",
        "数据链路层", "物理层", "网络层", "传输层", "应用层",
    }
    # Patterns for DB titles that are noise (figure/table references, etc.)
    DB_META_RE = re.compile(
        r"^(标题\d|图\d|表\d|第\d+行|第\d+图|R\d\s)"
    )
    DB_SKIP_KEYWORDS = {"2024", "2025", "2026", "2027", "Forouzan", "Tanenbaum"}

    seen_titles: set[str] = set()
    knowledge_points: list[dict[str, Any]] = []

    for i, chunk_text in enumerate(chunks[:10]):
        # Priority 1: use chunk title from DB if it's meaningful
        title = ""
        if i < len(chunk_titles):
            db_title = chunk_titles[i].strip()
            # Only use DB title if it's not a course name or broad concept
            if db_title and db_title not in BROAD_DB_TITLES:
                # Skip DB titles that are figure/table/meta references
                if DB_META_RE.match(db_title):
                    db_title = ""
                # Skip DB titles containing year keywords
                elif any(kw in db_title for kw in DB_SKIP_KEYWORDS):
                    db_title = ""
                # Skip DB titles that are just numbers/symbols
                elif re.match(r"^[\d\s\.\-]+$", db_title):
                    db_title = ""
                if db_title:
                    # Strip chapter/section prefix from DB title
                    cleaned_db = re.sub(
                        r"^(第[一二三四五六七八九十\d]+[章节]\s*|"
                        r"\d+[\.\-]\d+(?:[\.\-]\d+)*\s*|"
                        r"Chapter\s+\d+\s*)", "", db_title
                    ).strip()
                    title = cleaned_db if cleaned_db else db_title

        # Priority 2: extract a meaningful title from chunk text
        if not title:
            title = _extract_title_from_chunk(chunk_text, i)

        # Skip duplicate titles
        base_title = title[:30]
        if base_title in seen_titles:
            # Try extracting a different title from subsequent lines
            for offset in range(1, 5):
                remaining = chunk_text.split("\n")[offset:]
                if remaining:
                    alt_title = _extract_title_from_chunk(
                        "\n".join(remaining), i
                    )
                    if alt_title[:30] not in seen_titles:
                        title = alt_title
                        break
            if base_title == title[:30]:
                title = f"{title}（{i + 1}）"

        seen_titles.add(title[:30])

        summary = _clean_summary(chunk_text.strip()[:150])

        knowledge_points.append({
            "title": title,
            "summary": summary,
            "importance": 5 if i == 0 else 4,
            "source_chunk_ids": [i + 1],
            "exam_style": "简答题/选择题",
            "review_action": f"重读片段{i + 1}的相关内容。",
        })

    # If only one chunk was found, split it into at least 2 knowledge points
    if len(knowledge_points) < 2 and chunks:
        text = chunks[0].strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) >= 2:
            knowledge_points = [
                {
                    "title": _extract_title_from_chunk(lines[0], 0),
                    "summary": lines[0][:100],
                    "importance": 5,
                    "source_chunk_ids": [1],
                    "exam_style": "简答题/选择题",
                    "review_action": "重读片段1的相关内容。",
                },
                {
                    "title": _extract_title_from_chunk(lines[1], 1),
                    "summary": lines[1][:100],
                    "importance": 4,
                    "source_chunk_ids": [1],
                    "exam_style": "简答题/选择题",
                    "review_action": "重读片段1的相关内容。",
                },
            ]

    return {"knowledge_points": knowledge_points}


def _mock_planner(prompt: str = "") -> dict[str, Any]:
    """Generate a context-aware mock study plan from the prompt.

    Parses the goal and course names from the planner prompt so the
    generated tasks reference the user's actual courses instead of
    hardcoded "机器学习".
    """
    # Extract course names from the prompt (format: "## 可用课程（courses）\nA、B、C")
    course_match = re.search(r"可用课程.*?\n(.+?)(?:\n|$)", prompt)
    course_names: list[str] = []
    if course_match:
        raw = course_match.group(1).strip()
        course_names = [c.strip() for c in re.split(r"[、,，]", raw) if c.strip()]

    # Extract the goal from the prompt (format: "针对用户目标 `xxx`")
    goal_match = re.search(r"用户目标\s*[`「『]?(.+?)[`」』]?\s*[，,]", prompt)
    goal_text = goal_match.group(1).strip() if goal_match else "复习课程核心内容"

    if not course_names:
        course_names = ["默认课程"]

    primary_course = course_names[0]

    # Build tasks spread across the available courses
    task_templates = [
        ("复习核心概念", "review", 60, 5, "能口述核心概念并举例。"),
        ("完成配套练习", "practice", 45, 4, "习题正确率 ≥ 80%。"),
        ("梳理知识框架", "review", 90, 4, "能画出知识结构图。"),
        ("重难点专项突破", "practice", 60, 5, "能独立解决典型难题。"),
        ("阶段性自测", "practice", 45, 3, "自测得分 ≥ 70%。"),
    ]

    tasks = []
    for i, (title, task_type, minutes, priority, acceptance) in enumerate(task_templates):
        course_name = course_names[i % len(course_names)]
        tasks.append({
            "course_name": course_name,
            "title": title,
            "task_type": task_type,
            "estimate_minutes": minutes,
            "priority": priority,
            "acceptance": acceptance,
        })

    return {
        "goal_title": goal_text,
        "deadline": "2026-07-20",
        "daily_minutes": 120,
        "tasks": tasks,
    }


def _mock_task_decompose(prompt: str = "") -> dict[str, Any]:
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


def _mock_multi_course_schedule(prompt: str = "") -> dict[str, Any]:
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


def _mock_quiz_generate(prompt: str = "") -> dict[str, Any]:
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


def _mock_citation_verify(prompt: str = "") -> dict[str, Any]:
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


def _mock_concept_compare(prompt: str = "") -> dict[str, Any]:
    """Mock concept_compare: return citations derived from evidence in the prompt.

    The prompt contains a ``证据片段: [...]`` line whose JSON array lists
    the evidence chunks. We parse it so the mock returns real chunk ids
    rather than empty citations.
    """
    chunk_ids: list[int] = []
    m = re.search(r"证据片段:\s*(\[.*\])", prompt)
    if m:
        try:
            chunks = json.loads(m.group(1))
            for c in chunks:
                if isinstance(c, dict) and "chunk_id" in c:
                    try:
                        chunk_ids.append(int(c["chunk_id"]))
                    except (TypeError, ValueError):
                        continue
        except (json.JSONDecodeError, TypeError):
            pass
    citations = [
        {"chunk_id": cid, "quote": f"证据片段 {cid}", "supports": "对比依据"}
        for cid in chunk_ids
    ]
    return {
        "concept_a": {"title": "概念 A", "explanation": "基于证据的概念 A 解析"},
        "concept_b": {"title": "概念 B", "explanation": "基于证据的概念 B 解析"},
        "similarities": ["两者在各自课程中均为核心概念"],
        "differences": [
            {"dimension": "所属课程", "a": "课程 A", "b": "课程 B"}
        ],
        "transfer_learning": ["可迁移的方法论"],
        "confusions": ["注意适用场景差异"],
        "exam_questions": ["简述两者的联系与区别"],
        "citations": citations,
        "insufficient_evidence": not bool(citations),
    }


_MOCK_BUILDERS = {
    "course_qa": _mock_course_qa,
    "outline": _mock_outline,
    "planner": _mock_planner,
    "task_decompose": _mock_task_decompose,
    "multi_course_schedule": _mock_multi_course_schedule,
    "quiz_generate": _mock_quiz_generate,
    "citation_verify": _mock_citation_verify,
    "concept_compare": _mock_concept_compare,
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
        "messages": [
            {
                "role": "system",
                "content": (
                    "你必须只输出合法 JSON，不要输出 Markdown，"
                    "不要输出解释文字，不要使用代码块标记。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
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

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - wrap any JSON parse failure
        snippet = (resp.text or "")[:300]
        raise RuntimeError(
            "LLM 服务返回的不是 JSON，可能 Base URL 指向网页/鉴权页/错误页。"
            f"响应片段: {snippet}"
        ) from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        snippet = str(data)[:300]
        raise RuntimeError(
            "LLM 响应不是 OpenAI Chat Completions 格式（缺少 choices）。"
            f"响应片段: {snippet}"
        ) from exc

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        snippet = (content or "")[:300]
        raise RuntimeError(
            "模型回复不是合法 JSON；请检查 prompt 约束或模型是否支持 JSON 输出。"
            f"模型回复片段: {snippet}"
        ) from exc


__all__ = ["call_llm", "call_llm_with_meta"]
