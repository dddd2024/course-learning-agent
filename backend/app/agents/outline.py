"""OutlineAgent — extracts structured knowledge points from course materials.

The agent:
1. Loads the ``outline`` prompt template and fills the ``{course_name}``
   and ``{retrieved_chunks}`` placeholders.
2. Calls ``call_llm`` with ``agent_type="outline"`` to get a structured
   JSON response with a ``knowledge_points`` list.
3. Reconciles each knowledge point's ``source_chunk_ids`` against the
   actual chunk ids passed in (the mock LLM returns placeholder strings
   like ``"chunk_1"``; the real LLM may return ids that need validating).
4. Computes the final ``importance`` by combining the LLM-given base
   score with rule-based adjustments (title keywords, cross-material
   occurrence) per the design doc §12.2.
5. Returns a list of dicts ready for persistence / API response.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.llm import call_llm
from app.agents.prompt_loader import load_prompt
from app.models.course import Course
from app.models.material import Material
from app.models.material_chunk import MaterialChunk

# Keywords that signal a knowledge point is likely exam-relevant.
_IMPORTANCE_KEYWORDS = ("重点", "考试", "例题")

_REQUIRED_FIELDS = (
    "title",
    "summary",
    "importance",
    "source_chunk_ids",
    "exam_style",
    "review_action",
)

# --- Text cleaning for knowledge point titles and summaries ---

# Meaningless symbols commonly found in PDF extracts
_NOISE_SYMBOLS = re.compile(r"[□☐◆■►●○▪▫▶▷◇★☆▼▽▲△]")
# Date patterns: "2026年春", "2026年5月", "2024年"
_DATE_PATTERN = re.compile(r"\d{4}年(?:\d+月)?(?:春|秋|夏|冬)?")
# Standalone year (e.g. "2026 " at start of title)
_YEAR_ONLY = re.compile(r"\b\d{4}\b")
# Page references: "第3页", "P15", "[Forouzan]"
_PAGE_REF = re.compile(r"第\d+页|P\d+|\[[A-Za-z]+\]")
# Chapter/section prefix: "第五章 ", "第3章 ", "5.1.3 "
_CHAPTER_PREFIX = re.compile(r"^第[一二三四五六七八九十\d]+章\s*")
_SECTION_PREFIX = re.compile(r"^[\d.]+\s+")
# Institution/meta info
_META_INFO = re.compile(r"网络空间安全学院|计算机(?:网络|操作系统|数据结构|数据库)")
# Multiple whitespace
_MULTI_WS = re.compile(r"[ \t]+")


def _clean_text(text: str) -> str:
    """Remove noise symbols, dates, page refs, chapter prefixes, and normalize whitespace."""
    if not text:
        return ""
    result = _NOISE_SYMBOLS.sub("", text)
    result = _DATE_PATTERN.sub("", result)
    result = _PAGE_REF.sub("", result)
    result = _META_INFO.sub("", result)
    result = _MULTI_WS.sub(" ", result)
    # Collapse multiple newlines into single space
    result = re.sub(r"\n+", " ", result)
    return result.strip()


def _clean_title(title: str) -> str:
    """Clean a knowledge point title: remove noise + chapter/year prefixes."""
    if not title:
        return ""
    result = _clean_text(title)
    # Remove standalone year numbers (e.g. "2026 Chapter3" → "Chapter3")
    result = _YEAR_ONLY.sub("", result).strip()
    # Remove chapter prefix (e.g. "第五章 数据链路层" → "数据链路层")
    result = _CHAPTER_PREFIX.sub("", result).strip()
    # Remove section number prefix (e.g. "5.1.3 成帧方法" → "成帧方法")
    result = _SECTION_PREFIX.sub("", result).strip()
    # Remove dedup suffix (e.g. "标题（4）" → "标题")
    result = re.sub(r"（\d+）$", "", result).strip()
    return result


# Titles that are too broad (chapter-level, not specific concepts)
_TOO_BROAD_TITLES = {
    "数据链路层", "物理层", "网络层", "传输层", "应用层",
    "计算机网络", "操作系统", "数据结构", "数据库",
    "第五章", "第三章", "第四章", "第一章", "第二章",
    "信道", "帧", "协议", "网络", "分组",
    "Chapter3 Transport Layer", "Chapter1 Introduction",
    "Date", "内容提要", "教学要求及内容",
}

# Patterns that indicate a title is noise (not a real knowledge point)
_NOISE_TITLE_PATTERNS = [
    re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),  # IP address
    re.compile(r"^[\d\.\s-]+$"),  # only numbers/dots/dashes
    re.compile(r"^\d{4}\s"),  # starts with year
    re.compile(r"^(标题\d|图\d|表\d|第\d+行)"),  # figure/table/meta refs
    re.compile(r"^R\d\s"),  # router labels like "R3 R2"
    re.compile(r"^[\d]+\s+更高层"),  # "13 更高层" style noise
    # Pure-English multi-word titles (likely OCR noise, not real concepts)
    # Short English abbreviations like "CSMA/CD" or "TCP/IP" still pass
    re.compile(r"^[A-Za-z][A-Za-z\s/]{10,}$"),
]


def _format_chunks(chunks: list[dict]) -> str:
    """Render chunks into a readable prompt section."""
    if not chunks:
        return "（未检索到相关资料片段）"
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        page = chunk.get("page_no")
        page_str = f"，页码 {page}" if page is not None else ""
        title = chunk.get("title") or ""
        title_str = f"，标题：{title}" if title else ""
        lines.append(
            f"[片段{i}] chunk_id={chunk.get('chunk_id')}{page_str}{title_str}\n"
            f"{chunk.get('text', '')}"
        )
    return "\n\n".join(lines)


def calculate_importance(
    llm_importance: int,
    title: str,
    source_chunk_ids: list,
    chunks: list[dict],
) -> int:
    """Compute the final importance (1-5) from the LLM score + rule bonuses.

    Per design doc §12.2, importance is::

        min(5, llm_importance
              + (1 if title contains 重点/考试/例题 else 0)
              + (1 if appears in >=2 different materials else 0))

    The ``weak_point_error_count`` term is omitted in this initial version
    because weak-point data is not yet available.
    """
    importance = llm_importance

    # Title-keyword bonus.
    if any(kw in (title or "") for kw in _IMPORTANCE_KEYWORDS):
        importance += 1

    # Cross-material bonus: a point sourced from chunks in >=2 materials
    # is likely more central to the course.
    chunk_material_map = {
        c.get("chunk_id"): c.get("material_id") for c in chunks
    }
    material_ids: set = set()
    for cid in source_chunk_ids or []:
        mid = chunk_material_map.get(cid)
        if mid is not None:
            material_ids.add(mid)
    if len(material_ids) >= 2:
        importance += 1

    return min(5, max(1, importance))


def _reconcile_chunk_ids(
    raw_ids: list, valid_ids: list
) -> list:
    """Keep only source_chunk_ids that exist in ``valid_ids``.

    Falls back to all ``valid_ids`` when none match (e.g. the mock LLM
    returns placeholder strings like ``"chunk_1"``).
    """
    valid_set = set(valid_ids)
    matched = [cid for cid in (raw_ids or []) if cid in valid_set]
    if matched:
        return matched
    return list(valid_ids)


def _fetch_chunks(db: Session, course_id: int) -> list[dict]:
    """Load ready-material chunks for a course as agent input dicts.

    Filters out chunks with very short text (< 30 chars) that are
    typically cover pages or page headers (e.g. "计算机网络"), then
    evenly samples up to MAX_CHUNKS representative chunks.
    """
    MAX_CHUNKS = 50
    MIN_TEXT_LEN = 30
    rows = (
        db.query(MaterialChunk)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(
            MaterialChunk.course_id == course_id,
            Material.status == "ready",
        )
        .order_by(MaterialChunk.chunk_index.asc())
        .all()
    )
    # Filter out chunks with very short text (cover pages, headers)
    rows = [r for r in rows if r.text and len(r.text.strip()) >= MIN_TEXT_LEN]
    # Evenly sample MAX_CHUNKS items from the filtered list
    if len(rows) > MAX_CHUNKS:
        step = len(rows) / MAX_CHUNKS
        sampled = [rows[int(i * step)] for i in range(MAX_CHUNKS)]
        rows = sampled
    return [
        {
            "chunk_id": c.id,
            "text": c.text,
            "material_id": c.material_id,
            "title": c.title,
            "page_no": c.page_no,
        }
        for c in rows
    ]


def generate(
    db: Session,
    course_id: int,
    course_name: str | None = None,
    chunks: list[dict] | None = None,
    user_config: dict | None = None,
) -> list[dict]:
    """Extract structured knowledge points for a course.

    Args:
        db: SQLAlchemy session.
        course_id: Course to extract points for.
        course_name: Display name of the course. Fetched from DB if None.
        chunks: Pre-fetched chunk dicts. Loaded from DB if None.
        user_config: Optional per-user LLM config dict. When supplied,
            it is forwarded to :func:`call_llm` so the call uses the
            user's enabled provider config.

    Returns:
        A list of dicts, each with ``title``, ``summary``,
        ``importance``, ``source_chunk_ids``, ``exam_style``,
        ``review_action``.
    """
    if course_name is None:
        course = (
            db.query(Course).filter(Course.id == course_id).first()
        )
        course_name = course.name if course else ""
    if chunks is None:
        chunks = _fetch_chunks(db, course_id)

    template = load_prompt("outline")
    prompt = template.format(
        course_name=course_name,
        retrieved_chunks=_format_chunks(chunks),
    )

    output = call_llm(
        prompt, agent_type="outline", user_config=user_config
    )
    raw_points = output.get("knowledge_points", [])

    valid_chunk_ids = [c["chunk_id"] for c in chunks]

    results: list[dict[str, Any]] = []
    for point in raw_points:
        title = _clean_title(point.get("title", ""))
        summary = _clean_text(point.get("summary", ""))

        # Skip knowledge points with too-broad titles
        if title in _TOO_BROAD_TITLES:
            continue
        # Skip empty titles after cleaning
        if not title or len(title) < 2:
            continue
        # Skip titles that are just chapter numbers (e.g. "5.1", "3.2.1")
        if re.match(r"^[\d.]+$", title):
            continue
        # Skip titles that match noise patterns (IP addresses, pure numbers, etc.)
        if any(p.search(title) for p in _NOISE_TITLE_PATTERNS):
            continue

        source_ids = _reconcile_chunk_ids(
            point.get("source_chunk_ids", []), valid_chunk_ids
        )
        llm_importance = point.get("importance", 3)
        try:
            llm_importance = int(llm_importance)
        except (TypeError, ValueError):
            llm_importance = 3
        importance = calculate_importance(
            llm_importance,
            title,
            source_ids,
            chunks,
        )
        results.append(
            {
                "title": title,
                "summary": summary,
                "importance": importance,
                "source_chunk_ids": source_ids,
                "exam_style": point.get("exam_style", ""),
                "review_action": point.get("review_action", ""),
            }
        )
    return results


__all__ = ["generate", "calculate_importance"]
