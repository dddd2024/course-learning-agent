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

import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.agents.llm import call_llm_with_meta
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
# Unicode Private Use Area characters (PPT font icons extracted as text)
_PUA_CHARS = re.compile(r"[\ue000-\uf8ff]")
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
    """Remove noise symbols, PUA chars, dates, page refs, chapter prefixes, and normalize whitespace."""
    if not text:
        return ""
    result = _NOISE_SYMBOLS.sub("", text)
    result = _PUA_CHARS.sub("", result)
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


def _normalize_title(title: str) -> str:
    """Normalize a knowledge point title to a concept-style phrase.

    Converts question-style titles to concept phrases and filters out
    invalid titles (chapter numbers, single English words).

    - "为什么需要X?" → "X的必要性"
    - "什么是X?" → "X"
    - "为什么X?" → "X的原因"
    - "第N章" / "第N章 " → "" (filtered, chapter number only)
    - "Date" / single English word → "" (filtered, noise)
    - "总结：交换机的工作过程" → "交换机的工作过程"
    """
    if not title:
        return ""
    title = title.strip()

    # Strip leading non-alphanumeric, non-CJK characters (PUA remnants,
    # bullet points, spaces) so section number regex can match
    title = re.sub(r"^[^\w\u4e00-\u9fff]+", "", title).strip()

    # Strip chapter/section prefix: "第9章 磁盘存储器管理" → "磁盘存储器管理"
    title = re.sub(
        r"^第[\d一二三四五六七八九十]+章\s*", "", title
    ).strip()
    title = re.sub(
        r"^第[\d一二三四五六七八九十]+节\s*", "", title
    ).strip()
    # Strip section number prefix: "7.1 物理层概述" → "物理层概述"
    title = re.sub(r"^[\d]+[\.\-][\d]+(?:[\.\-]\d+)*\s*", "", title).strip()

    # Filter chapter-number-only titles (e.g. "第10章", "第五章")
    # (after stripping, if nothing remains, it was chapter-number-only)
    if not title:
        return ""
    if re.match(r"^第[\d一二三四五六七八九十]+章$", title):
        return ""

    # Filter single English words (noise like "Date", "Chapter3")
    if re.match(r"^[A-Za-z]\w{0,15}$", title) and not re.search(
        r"[/\u4e00-\u9fff]", title
    ):
        return ""

    # Strip meta prefixes: "总结：", "小结：", "概述：", "示例：", "复习："
    title = re.sub(
        r"^(总结|小结|概述|示例|备注|注意|提示|引言|前言|复习|回顾)[:：]\s*", "", title
    ).strip()

    # Convert "为什么需要X?" → "X的必要性"
    m = re.match(r"^为什么需要(.+?)\??$", title)
    if m:
        inner = m.group(1).strip().rstrip("?？")
        return f"{inner}的必要性"

    # Convert "什么是X?" → "X"
    m = re.match(r"^什么是(.+?)\??$", title)
    if m:
        return m.group(1).strip().rstrip("?？")

    # Convert "为什么X?" → "X的原因"
    m = re.match(r"^为什么(.+?)\??$", title)
    if m:
        inner = m.group(1).strip().rstrip("?？")
        return f"{inner}的原因"

    return title


def _is_valid_concept_title(title: str) -> bool:
    """Check if a title is a valid concept name (not OCR noise or data)."""
    if not title or len(title) < 2:
        return False
    # Check against noise patterns
    if any(p.search(title) for p in _NOISE_TITLE_PATTERNS):
        return False
    # Check against too-broad titles
    if title in _TOO_BROAD_TITLES:
        return False
    # Reject titles that are just numbers/section numbers
    if re.match(r"^[\d.]+$", title):
        return False
    # Reject sentence-style titles: "X是Y的Z" (contains 是 as a copula verb
    # in the middle, indicating a sentence not a concept name)
    if re.search(r".{2,}是.{2,}", title) and len(title) > 8:
        return False
    # Reject list-style titles: contains 3+ "、" separators (a list, not a concept)
    if title.count("、") >= 3:
        return False
    # Reject sentence-style titles: contains "，" (comma) indicating
    # explanatory text rather than a concept name
    if title.count("，") >= 2:
        return False
    # Reject overly long titles (>20 chars) that are likely sentence fragments
    if len(title) > 20:
        return False
    # --- Stricter quality checks for large chunk sets ---
    # Must contain at least one CJK character, a known English abbreviation
    # (2+ uppercase letters like TCP, DNS, HTTP, ARP, VLAN), or a technical
    # term with a slash (I/O, TCP/IP, Client/Server, HTTP/2).
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", title))
    has_abbr = bool(re.search(r"[A-Z]{2,}", title))
    has_tech_slash = bool(re.search(r"[A-Za-z]/[A-Za-z0-9]", title))
    if not (has_cjk or has_abbr or has_tech_slash):
        return False
    # Reject titles that look like raw data: IP addresses, email addresses
    if re.search(r"\d+\.\d+\.\d+\.\d+", title):
        return False
    if "@" in title:
        return False
    # Reject titles that are table rows (multiple space-separated short tokens)
    if len(re.findall(r"\S+\s+\S+\s+\S+\s+\S+", title)) > 0:
        return False
    # Reject titles with formula/math symbols
    if re.search(r"[×÷∞∑√≈≤≥≠±]", title):
        return False
    # Reject titles starting with digits followed by space (table data)
    if re.match(r"^\d+\s+\S", title):
        return False
    # Reject titles that look like URLs (http://, https://, ftp://, www.)
    if re.match(r"^(?:https?://|ftp://|www\.)", title, re.IGNORECASE):
        return False
    # Reject file paths starting with drive letters (C:\, D:/, etc.)
    if re.match(r"^[A-Za-z]:[\\/]", title):
        return False
    # Reject domain-like strings (example.com, site.cn, school.edu)
    if re.search(r"\.(?:com|cn|edu|org|net)\b", title, re.IGNORECASE):
        return False
    # Reject titles that are just English words with numbers (like "Chapter1 Introduction 68")
    if re.match(r"^[A-Za-z]+\d*\s+[A-Za-z]+\s+\d+", title):
        return False
    return True


# Titles that are too broad (chapter-level, not specific concepts)
_TOO_BROAD_TITLES = {
    "数据链路层", "物理层", "网络层", "传输层", "应用层",
    "计算机网络", "操作系统", "数据结构", "数据库",
    "第五章", "第三章", "第四章", "第一章", "第二章",
    "信道", "帧", "协议", "网络", "分组",
    "Chapter3 Transport Layer", "Chapter1 Introduction",
    "Date", "内容提要", "教学要求及内容",
    # Single-word concepts that are too broad
    "交换", "拥塞", "带宽", "简单", "吞吐量", "目的主机",
    "网卡", "小结", "总结", "概述", "小结", "总结",
    "封装", "路由", "转发", "差错控制", "差错检测",
    "电子邮件", "文件传输", "网络应用", "网络互连",
    "网络核心", "网络边缘", "教学目标", "教学要求",
    "物理地址", "IP地址", "端口号", "IP网络",
    "本地环路", "主机域名", "地址转换", "DHCP服务器",
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
    # Technical terms with slashes (CSMA/CD, TCP/IP, Client/Server) are NOT
    # caught here because the slash marks them as a compound term.
    re.compile(r"^[A-Za-z][A-Za-z\s]{10,}$"),
    # Diagram labels: single uppercase letters with spaces like "A YX B Z"
    re.compile(r"^[A-Z](\s+[A-Z])+"),
    # Titles starting with common OCR artifacts
    re.compile(r"^[的个么什是对于在]\s*"),  # incomplete Chinese fragments
    # "A 的..." style diagram descriptions
    re.compile(r"^[A-Z]\s+的"),
    # Hex/technical noise like "标志字段F为0x7E"
    re.compile(r"0x[0-9A-Fa-f]"),
    # Sentence fragments ending with period/question mark
    re.compile(r"[。？?]\s*$"),
    # Explanatory text with "前者...后者..." pattern
    re.compile(r"前者.*后者"),
    # Sentence fragments starting with common verbs/particles
    re.compile(r"^(用来|每个|这种|这类|这种|其中|通过|为了|由于|用于)"),
    # --- New patterns for large chunk set filtering ---
    # Meta info: disclaimers, author info, citations
    re.compile(r"(讲义中|课件制作|图片来源|引用时标记|参考文献|教材所附)"),
    # Example/instructional text
    re.compile(r"^(你|家里|例如|比如|假设|假设有|设有|设有一个)"),
    # Incomplete fragments ending with ellipsis or trailing comma
    re.compile(r"[…；，、]\s*$"),
    # Titles that are just "第N段" or "第N行" style references
    re.compile(r"^第[\d一二三四五六七八九十]+(段|行|句|页)"),
    # Acknowledgment/reference style: "April ，" or "[RFC]"
    re.compile(r"^(April|RFC|January|March)\b", re.IGNORECASE),
    # Chapter labels with page numbers: "Chapter1 Introduction 68"
    re.compile(r"^Chapter\d", re.IGNORECASE),
    # Table cell content: "选项字段名 功能"
    re.compile(r"^[A-Za-z\u4e00-\u9fff]+\s+(功能|特点|说明|含义)"),
    # Meta labels like "知识点46", "知识点2"
    re.compile(r"^知识点\d"),
    # Titles with specific institution names (examples, not concepts)
    re.compile(r"(北邮|北京邮电|清华大学|北京大学|中科院)"),
    # Titles starting with lowercase English letter followed by CJK
    re.compile(r"^[a-z]\s+[\u4e00-\u9fff]"),
    # Incomplete fragments with unmatched closing bracket
    re.compile(r"[\)）]\s*$"),
    # Sentence definitions: "X就叫Y" or "X称为Y"
    re.compile(r"(就叫|称为|叫做)"),
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

    Invalid model references are deliberately dropped.  Binding a concept to
    every available chunk turns an ungrounded answer into fabricated evidence.
    """
    valid_set = set(valid_ids)
    # OpenAI-compatible providers frequently serialize numeric JSON values as
    # strings. Canonicalising an exact decimal representation back to an
    # existing database id preserves the model's evidence binding; it does not
    # add a source or widen the evidence set.
    canonical_ids = {str(value): value for value in valid_set}
    matched: list = []
    for raw_id in raw_ids or []:
        raw_text = str(raw_id).strip()
        label_match = re.fullmatch(r"chunk_id\s*[=_]\s*(\d+)", raw_text, re.IGNORECASE)
        candidate = raw_id if raw_id in valid_set else canonical_ids.get(
            label_match.group(1) if label_match else raw_text
        )
        if candidate in valid_set and candidate not in matched:
            matched.append(candidate)
    return matched


def _fetch_chunks(db: Session, course_id: int) -> list[dict]:
    """Load ready-material chunks for a course as agent input dicts.

    Samples up to MAX_PER_MATERIAL chunks per material (chapter) so that
    knowledge points cover ALL chapters of the course. With 8 materials
    and 15 chunks each, we get ~120 chunks — enough for comprehensive
    coverage without overwhelming the title extraction.
    """
    MIN_TEXT_LEN = 30
    MAX_PER_MATERIAL = 25

    rows = (
        db.query(MaterialChunk)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(
            MaterialChunk.course_id == course_id,
            MaterialChunk.is_active == 1,
            MaterialChunk.is_indexable == 1,
            Material.status == "ready",
        )
        .order_by(MaterialChunk.material_id, MaterialChunk.chunk_index.asc())
        .all()
    )
    # Filter out chunks with very short text (cover pages, headers)
    rows = [r for r in rows if r.text and len(r.text.strip()) >= MIN_TEXT_LEN]

    # Group by material_id and sample evenly within each material
    by_material: dict[int, list] = defaultdict(list)
    for r in rows:
        by_material[r.material_id].append(r)

    sampled: list = []
    for material_id, material_chunks in by_material.items():
        if len(material_chunks) <= MAX_PER_MATERIAL:
            sampled.extend(material_chunks)
        else:
            # Evenly sample MAX_PER_MATERIAL chunks from this material
            step = len(material_chunks) / MAX_PER_MATERIAL
            sampled.extend(
                material_chunks[int(i * step)]
                for i in range(MAX_PER_MATERIAL)
            )

    return [
        {
            "chunk_id": c.id,
            "text": c.text,
            "material_id": c.material_id,
            "title": c.title,
            "page_no": c.page_no,
        }
        for c in sampled
    ]


class OutlineContractError(RuntimeError):
    """Raised when a real outline cannot satisfy the minimum evidence contract."""


def evaluate_outline_contract(points: list[dict], source_chunks: list[dict]) -> dict[str, int | bool]:
    """Evaluate the output contract without inventing or splitting concepts."""
    valid_ids = {chunk.get("chunk_id") for chunk in source_chunks}
    titles: list[str] = []
    missing_source_count = 0
    source_ids: set[Any] = set()
    for point in points:
        title = _normalize_title(_clean_title(str(point.get("title") or "")))
        sources = point.get("source_chunk_ids") or []
        matched = [source for source in sources if source in valid_ids]
        if not title or not _is_valid_concept_title(title) or not matched:
            missing_source_count += 1
            continue
        titles.append(re.sub(r"^[\d.、\-\s]+", "", title).strip().lower())
        source_ids.update(matched)
    duplicate_title_count = len(titles) - len(set(titles))
    valid_count = len(titles)
    return {
        "valid_count": valid_count,
        "missing_source_count": missing_source_count,
        "duplicate_title_count": duplicate_title_count,
        "distinct_source_count": len(source_ids),
        "passed": valid_count >= 2 and missing_source_count == 0 and duplicate_title_count == 0,
    }


def _repair_results(raw_points: list[dict], chunks: list[dict]) -> list[dict[str, Any]]:
    """Apply the same validation pipeline to a model-provided repair output."""
    valid_chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for point in raw_points:
        title = _normalize_title(_clean_title(point.get("title", "")))
        summary = _clean_text(point.get("summary", ""))
        if (not title or title in _TOO_BROAD_TITLES or not _is_valid_concept_title(title)
                or title in seen_titles):
            continue
        source_ids = _reconcile_chunk_ids(point.get("source_chunk_ids", []), valid_chunk_ids)
        if not source_ids:
            continue
        seen_titles.add(title)
        try:
            llm_importance = int(point.get("importance", 3))
        except (TypeError, ValueError):
            llm_importance = 3
        results.append({
            "title": title,
            "summary": summary,
            "importance": calculate_importance(llm_importance, title, source_ids, chunks),
            "source_chunk_ids": source_ids,
            "exam_style": point.get("exam_style", ""),
            "review_action": point.get("review_action", ""),
        })
    return _cluster_merge_titles(results)


def _is_observed_real_meta(meta: dict[str, Any]) -> bool:
    return (
        meta.get("meta_observed") is True
        and str(meta.get("actual_provider") or "").strip() not in {"", "mock", "unknown"}
        and bool(str(meta.get("actual_model") or "").strip())
        and meta.get("fallback_used") is False
        and meta.get("degraded") is False
    )


def generate(
    db: Session,
    course_id: int,
    course_name: str | None = None,
    chunks: list[dict] | None = None,
    user_config: dict | None = None,
    return_meta: bool = False,
) -> list[dict] | tuple[list[dict], dict]:
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

    output, meta = call_llm_with_meta(
        prompt, agent_type="outline", user_config=user_config
    )
    raw_points = output.get("knowledge_points", [])

    valid_chunk_ids = [c["chunk_id"] for c in chunks]

    results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()  # Deduplicate by normalized title
    for point in raw_points:
        title = _clean_title(point.get("title", ""))
        summary = _clean_text(point.get("summary", ""))

        # Normalize title: convert questions to concept phrases,
        # filter out chapter numbers and noise
        title = _normalize_title(title)

        # Skip knowledge points with too-broad titles
        if title in _TOO_BROAD_TITLES:
            continue
        # Skip empty titles after cleaning + normalization
        if not title or len(title) < 2:
            continue
        # Skip titles that are just chapter numbers (e.g. "5.1", "3.2.1")
        if re.match(r"^[\d.]+$", title):
            continue
        # Skip titles that match noise patterns (IP addresses, pure numbers, etc.)
        if any(p.search(title) for p in _NOISE_TITLE_PATTERNS):
            continue
        # Skip titles that fail concept validity check (sentence-style,
        # list-style, incomplete fragments)
        if not _is_valid_concept_title(title):
            continue
        # Skip duplicate titles (already added to results)
        if title in seen_titles:
            continue
        seen_titles.add(title)

        source_ids = _reconcile_chunk_ids(
            point.get("source_chunk_ids", []), valid_chunk_ids
        )
        if not source_ids:
            # A knowledge point without a validated source quote/id is not
            # eligible for the active course outline.
            continue
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

    # --- Title clustering: merge sub-topics into parent concepts ---
    # e.g., "RDT2.0：信道可能传输出错", "RDT2.0：要点", "RDT2.0: 操作示例"
    # all merge into the shortest representative: "RDT2.0"
    results = _cluster_merge_titles(results)

    initial_contract = evaluate_outline_contract(results, chunks)
    meta = dict(meta)
    meta["initial_contract"] = initial_contract
    meta["repair_attempted"] = False
    meta["repair_success"] = False
    meta["llm_call_count"] = 1
    if not initial_contract["passed"] and _is_observed_real_meta(meta):
        repair_template = load_prompt("outline_repair")
        repair_prompt = repair_template.format(
            course_name=course_name,
            retrieved_chunks=_format_chunks(chunks),
            original_output=json.dumps(output, ensure_ascii=False),
            failure_reason=(
                f"valid_count={initial_contract['valid_count']}, "
                f"missing_source_count={initial_contract['missing_source_count']}, "
                f"duplicate_title_count={initial_contract['duplicate_title_count']}"
            ),
        )
        repair_output, repair_meta = call_llm_with_meta(
            repair_prompt, agent_type="outline", user_config=user_config
        )
        repair_results = _repair_results(repair_output.get("knowledge_points", []), chunks)
        repair_contract = evaluate_outline_contract(repair_results, chunks)
        meta.update({
            "repair_attempted": True,
            "repair_success": bool(repair_contract["passed"] and _is_observed_real_meta(repair_meta)),
            "repair_contract": repair_contract,
            "repair_provider": repair_meta.get("actual_provider"),
            "repair_model": repair_meta.get("actual_model"),
            "repair_fallback_used": repair_meta.get("fallback_used"),
            "llm_call_count": 2,
        })
        if not _is_observed_real_meta(repair_meta):
            meta.update({
                "actual_provider": repair_meta.get("actual_provider"),
                "actual_model": repair_meta.get("actual_model"),
                "fallback_used": repair_meta.get("fallback_used"),
                "degraded": True,
            })
            raise OutlineContractError("OUTLINE_REPAIR_REAL_META_REQUIRED")
        if not repair_contract["passed"]:
            raise OutlineContractError(
                "OUTLINE_REPAIR_CONTRACT_FAILED:"
                f"valid_count={repair_contract['valid_count']},"
                f"missing_source_count={repair_contract['missing_source_count']},"
                f"duplicate_title_count={repair_contract['duplicate_title_count']}"
            )
        results = repair_results

    if return_meta:
        return results, meta
    return results


def _extract_root(title: str) -> str:
    """Extract the root concept from a title for clustering.

    "RDT2.0：信道可能传输出错" -> "rdt2.0"
    "DNS名字解析：迭代查询" -> "dns名字解析"
    "TCP连接管理：连接建立" -> "tcp连接管理"
    "CSMA/CD协议" -> "csma/cd协议"
    """
    # Split on common sub-topic separators
    parts = re.split(r"[：:—\-–(（]", title, maxsplit=1)
    root = parts[0].strip().lower()
    # Remove trailing numbers/punctuation
    root = re.sub(r"[\d]+$", "", root).strip()
    return root if len(root) >= 3 else title.lower().strip()


def _cluster_merge_titles(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge knowledge points that share a common root concept.

    Groups titles by their root prefix (text before the first separator
    like ：— -). Within each group, keeps the shortest title as the
    representative and merges source_chunk_ids and summaries.

    Only merges when a group has >= 3 members, to avoid over-merging
    distinct concepts that happen to share a short prefix.
    """
    if len(results) <= 1:
        return results

    # Group by root
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(results):
        root = _extract_root(r["title"])
        groups[root].append(i)

    merged: list[dict[str, Any]] = []
    used: set[int] = set()

    for root, indices in groups.items():
        # Only merge tightly related sub-topics.  A shared broad prefix can
        # legitimately cover different source sections (for example CRC,
        # stop-and-wait, and sliding-window under a data-link-layer heading);
        # collapsing those would destroy independently grounded concepts.
        distinct_sources = {
            source_id
            for i in indices
            for source_id in results[i].get("source_chunk_ids", [])
        }
        if len(indices) < 3 or len(distinct_sources) >= 2:
            for i in indices:
                if i not in used:
                    merged.append(results[i])
                    used.add(i)
            continue

        # Sort by title length (shortest = most general concept)
        indices.sort(key=lambda i: len(results[i]["title"]))

        # Keep the shortest title as representative
        rep = results[indices[0]].copy()

        # Merge source_chunk_ids and summaries from all members
        all_chunk_ids: list = []
        all_summaries: list[str] = []
        for i in indices:
            all_chunk_ids.extend(results[i].get("source_chunk_ids", []))
            s = results[i].get("summary", "")
            if s and s not in all_summaries:
                all_summaries.append(s)

        # Deduplicate chunk ids
        seen_ids: set = set()
        deduped_ids = []
        for cid in all_chunk_ids:
            if cid not in seen_ids:
                seen_ids.add(cid)
                deduped_ids.append(cid)

        rep["source_chunk_ids"] = deduped_ids
        rep["summary"] = all_summaries[0] if all_summaries else ""
        # Boost importance: concepts with many sub-topics are important
        rep["importance"] = min(5, rep.get("importance", 3) + 1)

        merged.append(rep)
        used.update(indices)

    # Add any results not yet processed (shouldn't happen, but safety)
    for i, r in enumerate(results):
        if i not in used:
            merged.append(r)

    return merged


__all__ = ["generate", "calculate_importance"]
