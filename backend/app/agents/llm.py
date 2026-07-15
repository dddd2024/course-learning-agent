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
from datetime import datetime
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
    timeout_seconds: float | None = None,
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
    # Task 9: allow certain agent types (e.g. concept_compare) to use a
    # longer timeout than the global default. The override is only used
    # when the caller did not supply their own ``timeout_seconds`` in
    # ``user_config``.
    timeout_override: float | None = timeout_seconds
    if timeout_override is None and agent_type == "concept_compare":
        timeout_override = getattr(
            settings, "LLM_CONCEPT_COMPARE_TIMEOUT_SECONDS", 120
        )

    # 1. Prefer the per-user config when supplied.
    if user_config is not None:
        try:
            result = _real_response(
                prompt, agent_type, schema, user_config, timeout_override
            )
            return result, {
                "meta_observed": True,
                "provider": "real",
                "model_name": user_config.get("model", ""),
                "requested_provider": "user", "requested_model": user_config.get("model", ""),
                "actual_provider": "user", "actual_model": user_config.get("model", ""),
                "fallback_used": False,
                "fallback_reason": None,
                "fallback_chain": [{"provider": "user", "status": "success"}], "degraded": False,
            }
        except Exception as exc:  # noqa: BLE001 - demo must stay up
            user_reason = str(exc) or exc.__class__.__name__
            logger.warning("User LLM config failed, trying system provider: %s", exc)
            # A quiz job has its own total budget and call counter.  Trying a
            # second real provider inside one counted call would bypass both,
            # so quiz generation falls directly to the deterministic mock.
            if agent_type != "quiz_generate" and (settings.LLM_PROVIDER or "mock").lower() == "real":
                try:
                    result = _real_response(prompt, agent_type, schema, None, timeout_override)
                    return result, {
                        "meta_observed": True,
                        "provider": "real", "model_name": settings.LLM_MODEL,
                        "requested_provider": "user", "requested_model": user_config.get("model", ""),
                        "actual_provider": "system", "actual_model": settings.LLM_MODEL,
                        "fallback_used": True, "fallback_reason": user_reason,
                        "fallback_chain": [{"provider":"user","status":"failed","reason":user_reason},{"provider":"system","status":"success"}],
                        "degraded": False,
                    }
                except Exception as system_exc:  # noqa: BLE001
                    user_reason = f"user: {user_reason}; system: {system_exc}"
            return _mock_response(agent_type, prompt), {
                "meta_observed": True,
                "provider": "mock", "model_name": "mock",
                "requested_provider": "user", "requested_model": user_config.get("model", ""),
                "actual_provider": "mock", "actual_model": "mock",
                "fallback_used": True, "fallback_reason": user_reason,
                "fallback_chain": [{"provider":"user","status":"failed","reason":user_reason},{"provider":"mock","status":"success"}],
                "degraded": True,
            }

    # 2. Otherwise defer to the system provider setting.
    provider = (settings.LLM_PROVIDER or "mock").lower()
    if provider == "real":
        try:
            result = _real_response(
                prompt, agent_type, schema, None, timeout_override
            )
            return result, {
                "meta_observed": True,
                "provider": "real",
                "model_name": settings.LLM_MODEL,
                "requested_provider": "system", "requested_model": settings.LLM_MODEL,
                "actual_provider": "system", "actual_model": settings.LLM_MODEL,
                "fallback_used": False,
                "fallback_reason": None,
                "fallback_chain": [{"provider":"system","status":"success"}], "degraded": False,
            }
        except Exception as exc:  # noqa: BLE001 - demo must stay up
            logger.warning(
                "System real LLM failed, falling back to mock: %s", exc
            )
            return _mock_response(agent_type, prompt), {
                "meta_observed": True,
                "provider": "mock",
                "model_name": "mock",
                "requested_provider": "system", "requested_model": settings.LLM_MODEL,
                "actual_provider": "mock", "actual_model": "mock",
                "fallback_used": True,
                "fallback_reason": str(exc) or exc.__class__.__name__,
                "fallback_chain": [{"provider":"system","status":"failed","reason":str(exc)},{"provider":"mock","status":"success"}], "degraded": True,
            }

    # 3. Mock provider (default, or unknown provider) keeps the demo alive.
    return _mock_response(agent_type, prompt), {
        "meta_observed": True,
        "provider": "mock",
        "model_name": "mock",
        "requested_provider": "mock", "requested_model": "mock",
        "actual_provider": "mock", "actual_model": "mock",
        "fallback_used": False,
        "fallback_reason": None,
        "fallback_chain": [{"provider":"mock","status":"success"}], "degraded": True,
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
        # Select the chunk with the most content (longest text), not just
        # the first one — the first chunk may be a short title chunk.
        sorted_chunks = sorted(chunks, key=lambda c: len(c[1].strip()), reverse=True)
        best_cid, best_text = sorted_chunks[0]
        best_text = best_text.strip()

        # Build answer from the best chunk, prioritising lines that contain
        # keywords from the question.
        question_lower = question.lower() if question else ""
        q_keywords = [c for c in question_lower if '\u4e00' <= c <= '\u9fff']
        lines = [l.strip() for l in best_text.split("\n") if l.strip() and len(l.strip()) >= 5]

        if q_keywords and lines:
            matching = [l for l in lines if any(kw in l.lower() for kw in q_keywords)]
            if matching:
                answer = matching[0][:200]
                if len(matching) > 1:
                    answer += " " + matching[1][:150]
            else:
                answer = best_text[:200]
        else:
            answer = best_text[:200]

        if len(best_text) > 200 and len(answer) <= 200:
            answer += "…"

        first_cid = best_cid
        first_text = best_text

        key_points: list[str] = []
        for cid, text in chunks[:3]:
            lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
            if lines:
                key_points.append(lines[0][:60])

        citations = [
            {
                "chunk_id": first_cid,
                "quote_text": first_text[:150],
                "claim_text": answer,
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


def _mock_material_overview(prompt: str = "") -> dict[str, Any]:
    """Produce an explicitly bounded guide from supplied evidence only."""
    snippets = re.findall(r"\[证据\d+[^\]]*\]\s*(.+?)(?=\n\n\[证据|\Z)", prompt, re.DOTALL)
    highlights = [re.sub(r"\s+", " ", snippet).strip()[:160] for snippet in snippets if snippet.strip()]
    if not highlights:
        return {"answer": "资料不足，无法生成内容速览。"}
    return {
        "answer": "本速览仅覆盖抽样资料片段，不代表整份资料。\n\n" + "\n".join(
            f"- {highlight}" for highlight in highlights[:5]
        )
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


def _truncate_to_concept(line: str) -> str:
    """Truncate a sentence-style line to a concept name.

    "快表 TLB 是页表的高速缓存..." → "快表 TLB"
    "CSMA/CD协议：用于以太网的介质访问控制" → "CSMA/CD协议"
    "数据链路层的主要功能，包括成帧..." → "数据链路层的主要功能"
    """
    # Split at copula verbs (是, 就是, 乃) — take subject
    for sep in ["就是", "是", "乃"]:
        if sep in line:
            parts = line.split(sep, 1)
            subject = parts[0].strip()
            if len(subject) >= 2:
                return subject[:30]
    # Split at colon — take concept before colon
    for sep in ["：", ":"]:
        if sep in line:
            parts = line.split(sep, 1)
            concept = parts[0].strip()
            if len(concept) >= 2:
                return concept[:30]
    # Split at comma — take first clause
    for sep in ["，", ",", "。", "；"]:
        if sep in line:
            parts = line.split(sep, 1)
            clause = parts[0].strip()
            if len(clause) >= 2:
                return clause[:30]
    return line[:30]


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

    # Extract chunk text and chunk_id from the prompt.
    # Capture chunk_id as group(1) and text as group(2) so we can use
    # the real DB chunk_id in source_chunk_ids instead of position indices.
    chunk_pattern = re.compile(
        r"\[片段\d+\]\s*chunk_id=(\d+)[^\n]*\n(.+?)(?=\n\n|\Z)",
        re.DOTALL,
    )
    chunk_matches = chunk_pattern.findall(prompt)
    chunks = [text for _cid, text in chunk_matches]
    chunk_ids = [int(cid) for cid, _text in chunk_matches]

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

    for i, chunk_text in enumerate(chunks):
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

        # Truncate sentence-style titles to concept names
        # e.g. "快表 TLB 是页表的高速缓存..." → "快表 TLB"
        if len(title) > 15 or re.search(r".{2,}是.{2,}", title):
            title = _truncate_to_concept(title)

        # Skip duplicate titles (use full title for dedup)
        if title in seen_titles:
            # Try extracting a different title from subsequent lines
            found_alt = False
            for offset in range(1, 5):
                remaining = chunk_text.split("\n")[offset:]
                if remaining:
                    alt_title = _extract_title_from_chunk(
                        "\n".join(remaining), i
                    )
                    if alt_title and alt_title not in seen_titles:
                        title = alt_title
                        found_alt = True
                        break
            if not found_alt:
                # Skip this chunk entirely - no unique title found
                continue

        seen_titles.add(title)

        # Generate a better summary: use first 2-3 meaningful lines instead
        # of just truncating to 150 chars.
        _lines = [l.strip() for l in chunk_text.strip().split("\n") if l.strip()]
        _meaningful = [
            l for l in _lines
            if l != title and len(l) >= 5
            and not re.match(r"^[\d\s\.\-:]+$", l)
        ][:3]
        if _meaningful:
            summary = "。".join(_meaningful)[:200]
        else:
            summary = _clean_summary(chunk_text.strip()[:200])

        knowledge_points.append({
            "title": title,
            "summary": summary,
            "importance": 5 if i == 0 else 4,
            "source_chunk_ids": [chunk_ids[i]] if i < len(chunk_ids) else [],
            "exam_style": "简答题/选择题",
            "review_action": f"重读片段{i + 1}的相关内容。",
        })

    # If only one chunk was found, split it into at least 2 knowledge points
    if len(knowledge_points) < 2 and chunks:
        text = chunks[0].strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) >= 2:
            # Extract concept-style titles from the full text, skipping
            # header/footer lines that _extract_title_from_chunk would skip.
            # Use the full text so the function can iterate over all lines
            # and find the first meaningful one.
            t1 = _extract_title_from_chunk(text, 0)
            # For t2, skip the first meaningful line and extract from the rest
            remaining_lines = lines[1:]
            t2 = _extract_title_from_chunk(
                "\n".join(remaining_lines), 1
            ) if remaining_lines else f"知识点2"
            if len(t1) > 15 or re.search(r".{2,}是.{2,}", t1):
                t1 = _truncate_to_concept(t1)
            if len(t2) > 15 or re.search(r".{2,}是.{2,}", t2):
                t2 = _truncate_to_concept(t2)
            # Skip generic fallback titles — better to have 1 good KP
            # than 2 KPs with placeholder titles.
            if t1.startswith("知识点") or t2.startswith("知识点"):
                pass  # Keep original knowledge_points (1 KP with good title)
            else:
                knowledge_points = [
                    {
                        "title": t1,
                        "summary": _clean_summary(text[:200]),
                        "importance": 5,
                        "source_chunk_ids": [chunk_ids[0]] if chunk_ids else [],
                        "exam_style": "简答题/选择题",
                        "review_action": "重读片段1的相关内容。",
                    },
                    {
                        "title": t2,
                        "summary": _clean_summary(
                            "\n".join(lines[1:])[:200] if len(lines) > 1 else text[:200]
                        ),
                        "importance": 4,
                        "source_chunk_ids": [chunk_ids[0]] if chunk_ids else [],
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
        ("学习课程资料", "learn", 45, 4, "阅读并确认课程资料的核心段落。"),
        ("复习核心概念", "review", 60, 5, "能口述核心概念并举例。"),
        ("完成配套测验", "quiz", 45, 4, "测验正确率 ≥ 80%。"),
        ("梳理知识框架", "review", 90, 4, "能画出知识结构图。"),
        ("重难点专项测验", "quiz", 60, 5, "测验正确率 ≥ 80%。"),
        ("阶段性自测", "quiz", 45, 3, "自测得分 ≥ 70%。"),
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
    goal = _extract_prompt_field(prompt, "学习目标:") or _extract_prompt_field(prompt, "目标:") or "学习目标"
    course = _extract_prompt_field(prompt, "课程:") or _extract_prompt_field(prompt, "课程名称:") or "当前课程"
    keyword = (goal or course).strip()[:24]
    return {
        "parent_task": f"完成{keyword}",
        "subtasks": [
            {
                "title": f"理解{course}相关资料：{keyword}",
                "task_type": "learn",
                "estimate_minutes": 40,
                "priority": 5,
                "acceptance": "能复述资料中的核心概念。",
                "depends_on": [],
            },
            {
                "title": f"整理{keyword}知识点并完成自测",
                "task_type": "review",
                "estimate_minutes": 30,
                "priority": 3,
                "acceptance": "能说明关键知识点及其关系。",
                "depends_on": [f"理解{course}相关资料：{keyword}"],
            },
        ],
    }


def _mock_multi_course_schedule(prompt: str = "") -> dict[str, Any]:
    courses_match = re.search(r"课程(?:列表)?[：:]\s*(.+)", prompt)
    courses = [x.strip() for x in re.split(r"[、,，]", courses_match.group(1)) if x.strip()] if courses_match else []
    courses = courses or ["当前课程"]
    deadline_match = re.search(r"截止(?:日期)?[：:]\s*(\d{4}-\d{2}-\d{2})", prompt)
    day = deadline_match.group(1) if deadline_match else datetime.now().strftime("%Y-%m-%d")
    budget_match = re.search(r"(?:每日|可用).*?(\d+)\s*分钟", prompt)
    budget = int(budget_match.group(1)) if budget_match else 60
    per_course = max(15, budget // len(courses))
    return {
        "schedule": [{"date": day, "course_name": course, "title": f"复习{course}资料并练习验证", "task_type": "review", "estimate_minutes": per_course, "priority": 4, "acceptance": "完成资料复习与自测。"} for course in courses],
        "unscheduled_tasks": [], "total_days": 1, "total_minutes": per_course * len(courses),
    }


def _mock_quiz_generate(prompt: str = "") -> dict[str, Any]:
    """Generate quiz questions from actual evidence chunks in the prompt.

    Parses the evidence chunks (format: ``[evidence_id={id} page={page}] text``)
    from the prompt and creates true/false and short-answer questions based on
    actual text from the chunks. Each question includes ``source_evidence``
    with ``chunk_id`` and ``quote_text`` that is a substring of the actual chunk
    text, so the grounding can be independently verified.

    V7.4-07: Parse requested question_count from prompt and generate enough
    questions to meet the demand (cycling through chunks if needed).
    """
    # CONTRACT_JSON is the production provider contract. Keep the legacy
    # prompt parsing only as a compatibility fallback for older callers.
    contract: dict[str, Any] = {}
    contract_match = re.search(
        r"CONTRACT_JSON\s*\n\s*(\{.*?\})\s*\n\s*CONTRACT_JSON_END",
        prompt,
        re.DOTALL,
    )
    if contract_match:
        try:
            decoded = json.loads(contract_match.group(1))
            contract = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            contract = {}
    count_match = re.search(r"生成\s*[`'\"]?(\d+)[`'\"]?\s*道", prompt)
    requested_count = int(contract.get("question_count") or (count_match.group(1) if count_match else 5))
    question_offset = max(0, int(contract.get("question_offset") or 0))
    requested_types = [
        str(value) for value in contract.get("question_types", [])
        if str(value) in {"choice", "multiple_choice", "true_false", "short_answer"}
    ]
    if not requested_types:
        type_match = re.search(r"仅生成以下题型：(.+?)。", prompt)
        requested_types = [
            name for name in ("choice", "multiple_choice", "true_false", "short_answer")
            if type_match and name in type_match.group(1)
        ] or ["choice", "true_false", "short_answer"]
    distribution = contract.get("difficulty_distribution")
    if isinstance(distribution, dict):
        bands = [
            band for band in ("easy", "medium", "hard")
            for _ in range(max(0, int(distribution.get(band, 0))))
        ]
    else:
        bands = []
    if len(bands) != requested_count:
        dist_match = re.search(r"(\d+)\s+easy,\s*(\d+)\s+medium,\s*(\d+)\s+hard", prompt)
        bands = (
            ["easy"] * int(dist_match.group(1)) + ["medium"] * int(dist_match.group(2)) + ["hard"] * int(dist_match.group(3))
            if dist_match else ["medium"] * requested_count
        )

    # Parse evidence chunks from the prompt.
    evidence_pattern = re.compile(
        # Preserve paragraph breaks within an evidence item.  The prompt's
        # next section starts with ``##`` and is the real boundary.
        r"\[evidence_id=(\d+)[^\]]*\]\s*(.+?)(?=\n\[evidence_id=|\n## |\Z)",
        re.DOTALL,
    )
    chunks_raw = evidence_pattern.findall(prompt)

    if not chunks_raw:
        return {"questions": [], "title": "测验"}

    # Build (chunk_id:int, text:str) pairs, filtering very short chunks.
    chunks: list[tuple[int, str]] = []
    for cid_str, text in chunks_raw:
        text = text.strip()
        if text and len(text) >= 10:
            chunks.append((int(cid_str), text))

    if not chunks:
        return {"questions": [], "title": "测验"}

    questions: list[dict[str, Any]] = []
    for index in range(requested_count):
        sequence_index = question_offset + index
        chunk_id, chunk_text = chunks[sequence_index % len(chunks)]
        lines = [line.strip() for line in chunk_text.splitlines() if len(line.strip()) >= 8]
        source_line = (lines[sequence_index % len(lines)] if lines else chunk_text.strip())[:160]
        if len(source_line) < 8:
            return {"questions": [], "title": "课程资料测验"}
        qtype = requested_types[index % len(requested_types)]
        quote = source_line
        base = {
            "difficulty": bands[index] if index < len(bands) else "medium",
            "explanation": "答案直接由课程资料中的来源引用支持。",
            "knowledge_point_ids": [f"kp_{sequence_index % len(chunks) + 1}"],
            "source_chunk_ids": [str(chunk_id)],
            "source_evidence": [{"chunk_id": chunk_id, "quote_text": quote}],
        }
        if qtype == "choice":
            questions.append({**base, "question_type": "single_choice", "stem": f"以下哪项与课程资料原文一致（第{sequence_index + 1}题）？", "options": [quote, f"并非：{quote}", f"与资料无关：{sequence_index + 1}", f"反向陈述：{quote[::-1]}"], "answer": "A", "rubric": []})
        elif qtype == "multiple_choice":
            midpoint = max(1, len(quote) // 2)
            left, right = quote[:midpoint], quote[midpoint:]
            questions.append({**base, "question_type": "multiple_choice", "stem": f"以下哪些片段直接来自课程资料（第{sequence_index + 1}题）？", "options": [left, right, f"资料未给出的结论：{sequence_index + 1}", f"不支持的反向结论：{sequence_index + 1}"], "answer": ["A", "B"], "rubric": []})
        elif qtype == "true_false":
            questions.append({**base, "question_type": "true_false", "stem": f"以下说法是否正确：{quote}", "options": [], "answer": True, "rubric": []})
        else:
            candidates = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", quote)
            answer = candidates[0] if candidates else quote[: max(3, len(quote) // 3)]
            questions.append({**base, "question_type": "short_answer", "stem": f"根据课程资料，写出与“{answer}”相关的关键内容（第{sequence_index + 1}题）。", "options": [], "answer": answer, "rubric": [{"criterion": f"包含关键词“{answer}”", "keywords": [answer], "weight": 1.0, "evidence_ids": [chunk_id], "required": True}]})
    return {"title": "课程资料测验", "questions": questions}


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
    """Mock concept_compare: parse concept titles/summaries from the prompt
    and generate a structured comparison with real content.

    The prompt is formatted with:
        概念 A: {title}
        概念 A 摘要: {summary}
        概念 B: {title}
        概念 B 摘要: {summary}
        证据片段: [{chunk_id, ...}, ...]
        用户关注点: {concept|exam|transfer}
    """
    # Parse concept titles and summaries from the prompt
    title_a = _extract_prompt_field(prompt, "概念 A:")
    summary_a = _extract_prompt_field(prompt, "概念 A 摘要:")
    title_b = _extract_prompt_field(prompt, "概念 B:")
    summary_b = _extract_prompt_field(prompt, "概念 B 摘要:")
    user_focus = _extract_prompt_field(prompt, "用户关注点:")

    # Parse evidence chunk ids
    chunk_ids: list[int] = []
    m = re.search(r"证据片段:\s*(\[.*?\])", prompt, re.DOTALL)
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

    # Mock output is evidence-extractive only.  It must not infer semantic
    # similarity from title characters or n-grams.
    from app.services.concept_graph_service import (
        _keyword_set, _jaccard, _cjk_chars,
    )
    kw_a = _keyword_set(summary_a)
    kw_b = _keyword_set(summary_b)
    overlap = _jaccard(kw_a, kw_b)
    shared_kws = kw_a & kw_b
    shared_chars = _cjk_chars(title_a) & _cjk_chars(title_b)

    similarities: list[str] = []

    # Generate meaningful differences
    differences: list[dict] = []

    # Extract distinguishing keywords (in A but not B, and vice versa)
    only_a = list(kw_a - kw_b)[:3]
    only_b = list(kw_b - kw_a)[:3]
    _ = (shared_kws, shared_chars, only_a, only_b)

    # Focus-specific content
    transfer_learning: list[str] = []
    confusions: list[str] = []
    exam_questions: list[str] = []

    # Intentionally leave all semantic-conclusion sections empty.

    return {
        "concept_a": {
            "title": title_a or "概念 A",
            "explanation": summary_a or "基于证据的概念解析",
        },
        "concept_b": {
            "title": title_b or "概念 B",
            "explanation": summary_b or "基于证据的概念解析",
        },
        "similarities": similarities,
        "differences": differences,
        "transfer_learning": transfer_learning,
        "confusions": confusions,
        "exam_questions": exam_questions,
        "citations": citations,
        "insufficient_evidence": not bool(citations),
    }


def _extract_prompt_field(prompt: str, field_name: str) -> str:
    """Extract a field value from a prompt line like '概念 A: xxx'.

    Returns the text after the field name up to the next newline.
    """
    pattern = re.escape(field_name) + r"\s*(.+?)(?:\n|$)"
    m = re.search(pattern, prompt)
    if m:
        return m.group(1).strip()
    return ""


def _heuristic_quality_score(text: str) -> tuple[float, str]:
    """Return (score, reason) using enhanced heuristics for chunk quality.

    Goes beyond _is_low_quality_chunk by also checking:
    - Sentence structure (presence of periods, conjunctions)
    - Information density (meaningful word ratio)
    - Content coherence (transitions between ideas)
    """
    import re as _re

    if not text or len(text.strip()) < 10:
        return 0.1, "内容过短，无实质信息"

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return 0.1, "内容为空"

    # 1. Line repetition check
    unique_ratio = len(set(lines)) / len(lines)
    if unique_ratio < 0.5:
        return 0.15, "行重复率高，疑似图表标签文本"

    # 2. Short-line stacking
    short_lines = sum(1 for l in lines if len(l) < 4)
    if len(lines) > 3 and short_lines / len(lines) > 0.6:
        return 0.15, "短行堆叠，疑似图表或编号文本"

    # 3. Vocabulary diversity
    cjk_chars = [c for c in text if "\u4e00" <= c <= "\u9fff" or c.isalpha()]
    if not cjk_chars:
        return 0.2, "无有效文字字符"
    unique_chars = len(set(cjk_chars))
    diversity = unique_chars / len(cjk_chars)
    if diversity < 0.3:
        return 0.2, "词汇多样性低，疑似重复文本"

    # 4. Sentence structure - look for sentence endings
    sentence_endings = text.count("。") + text.count("；") + text.count(".") + text.count(";")
    if sentence_endings == 0 and len(text) > 50:
        return 0.3, "无句尾标点，缺乏完整句子结构"

    # 5. Information density - meaningful CJK words (2+ consecutive CJK chars)
    cjk_sequences = _re.findall(r"[\u4e00-\u9fff]{2,}", text)
    meaningful_words = len(cjk_sequences)
    if len(text) > 100 and meaningful_words < 5:
        return 0.35, "有效词汇密度低"

    # 6. Noise patterns - years, page numbers, teacher info
    noise_patterns = [
        r"\d{4}年(?:春|秋|夏|冬)",
        r"第\d+页",
        r"^(?:主讲教师|教师)[:：]",
    ]
    noise_count = sum(len(_re.findall(p, text)) for p in noise_patterns)
    if noise_count > 2 and noise_count / max(len(lines), 1) > 0.3:
        return 0.4, "噪声内容占比高"

    # Passed all checks - assign score based on content quality
    if len(text) > 80 and sentence_endings >= 2 and diversity > 0.5:
        return 0.9, "内容完整，信息密度高"
    if len(text) > 30 and sentence_endings >= 1:
        return 0.7, "内容较为完整"
    return 0.55, "内容基本可用"


def _mock_chunk_quality(prompt: str = "") -> dict[str, Any]:
    """Evaluate chunk quality using enhanced heuristics.

    Parses chunks from the prompt and returns a quality score (0.0-1.0)
    and reason for each. This mock uses sentence structure, information
    density, and noise detection beyond the basic _is_low_quality_chunk rules.
    """
    chunk_pattern = re.compile(
        r"\[片段(\d+)\]\s*\n(.+?)(?=\n\n|\[片段\d+\]|\Z)",
        re.DOTALL,
    )
    matches = chunk_pattern.findall(prompt)

    if not matches:
        return {"evaluations": []}

    evaluations = []
    for idx_str, text in matches:
        idx = int(idx_str)
        text = text.strip()
        score, reason = _heuristic_quality_score(text)
        evaluations.append({
            "index": idx,
            "quality": round(score, 2),
            "reason": reason,
        })

    return {"evaluations": evaluations}


_MOCK_BUILDERS = {
    "course_qa": _mock_course_qa,
    "material_overview": _mock_material_overview,
    "outline": _mock_outline,
    "planner": _mock_planner,
    "task_decompose": _mock_task_decompose,
    "multi_course_schedule": _mock_multi_course_schedule,
    "quiz_generate": _mock_quiz_generate,
    "citation_verify": _mock_citation_verify,
    "concept_compare": _mock_concept_compare,
    "chunk_quality": _mock_chunk_quality,
}


def _real_response(
    prompt: str,
    agent_type: str,
    schema: dict | None,
    user_config: dict | None,
    timeout_override: int | None = None,
) -> dict[str, Any]:
    """Call an OpenAI-compatible ``/chat/completions`` API via httpx.

    The request body always carries ``response_format={"type":
    "json_object"}`` so the model returns parseable JSON. If the server
    rejects this field with a 400, the call is retried once without it
    to stay compatible with providers that do not support JSON mode.

    SEC-V3-01: Before making the HTTP request, the base URL is
    re-validated via :func:`validate_llm_base_url_request_time` to
    prevent DNS rebinding. Redirects are disabled, independent timeouts
    are used, and response size is limited (10 MB body / 100 KB
    headers). Authorization headers and API keys are never logged.

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
    timeout_override:
        Optional agent-specific timeout (seconds). Used only when
        ``user_config`` is ``None`` or does not contain its own
        ``timeout_seconds``. Callers like ``concept_compare`` pass a
        longer value here so first-call latency doesn't trip the global
        60s default (Task 9).

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
    from app.services.llm_config_security import (
        validate_llm_base_url_request_time,
    )

    if user_config is not None:
        base_url = user_config["base_url"]
        model = user_config["model"]
        api_key = user_config["api_key"]
        temperature = user_config.get("temperature", settings.LLM_TEMPERATURE)
        max_tokens = user_config.get("max_tokens", settings.LLM_MAX_TOKENS)
        # Task 9: use the agent-specific timeout override only when the
        # user_config does not specify its own ``timeout_seconds``.
        configured_timeout = user_config.get("timeout_seconds", settings.LLM_TIMEOUT_SECONDS)
        timeout = min(float(configured_timeout), float(timeout_override)) if timeout_override is not None else configured_timeout
    else:
        base_url = settings.LLM_BASE_URL
        model = settings.LLM_MODEL
        api_key = settings.LLM_API_KEY
        temperature = settings.LLM_TEMPERATURE
        max_tokens = settings.LLM_MAX_TOKENS
        timeout = min(float(settings.LLM_TIMEOUT_SECONDS), float(timeout_override)) if timeout_override is not None else settings.LLM_TIMEOUT_SECONDS

    # SEC-V3-01: request-time SSRF validation — re-resolve DNS and check
    # all resolved IPs before making the HTTP request.
    # When ALLOW_PRIVATE_LLM_ENDPOINTS is True (development/testing mode),
    # skip the request-time validation because private endpoints are already
    # permitted at config-save time and the DNS rebinding check is unnecessary.
    # Production mode (ALLOW_PRIVATE_LLM_ENDPOINTS=False) enforces strict
    # request-time SSRF validation.
    if not settings.ALLOW_PRIVATE_LLM_ENDPOINTS:
        is_valid, reason = validate_llm_base_url_request_time(base_url)
        if not is_valid:
            raise RuntimeError(
                f"SSRF protection blocked LLM request: {reason}"
            )

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

    # SEC-V3-01: independent timeouts and disabled redirects.
    http_timeout = httpx.Timeout(
        connect=30.0,
        read=120.0,
        write=30.0,
        pool=10.0,
    )
    # Use the shorter of the config timeout and the SSRF-mandated
    # read timeout, so a user-configured 5s timeout still works.
    if isinstance(timeout, (int, float)) and timeout < 120:
        http_timeout = httpx.Timeout(
            connect=min(30.0, timeout),
            read=timeout,
            write=min(30.0, timeout),
            pool=10.0,
        )

    max_body_bytes = 10 * 1024 * 1024  # 10 MB
    max_header_bytes = 100 * 1024     # 100 KB

    try:
        with httpx.Client(
            timeout=http_timeout,
            follow_redirects=False,
        ) as client:
            # First attempt asks for JSON-mode output.
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code == 400:
                # Some OpenAI-compatible backends reject response_format;
                # retry once without it so we still get a usable answer.
                body.pop("response_format", None)
                resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # SEC-V3-01: never log Authorization header or API key values.
        snippet = (exc.response.text or "")[:300]
        raise RuntimeError(
            f"LLM HTTP {exc.response.status_code}: {snippet}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"LLM 网络请求失败: {exc}"
        ) from exc

    # SEC-V3-01: response size limits.
    header_size = sum(
        len(k) + len(v) + 4 for k, v in resp.headers.items()
    )
    if header_size > max_header_bytes:
        raise RuntimeError(
            f"LLM 响应头超过 {max_header_bytes} 字节限制 "
            f"(实际: {header_size})"
        )
    if len(resp.content) > max_body_bytes:
        raise RuntimeError(
            f"LLM 响应体超过 {max_body_bytes} 字节限制 "
            f"(实际: {len(resp.content)})"
        )

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
