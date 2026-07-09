"""Retrieval strategies for the course learning assistant.

This module currently provides keyword-based search over
``material_chunks`` and reserves the interfaces for vector recall,
result merging, and re-ranking. The vector path is intentionally left
as a stub so downstream tasks (Task 11) can plug in an embedding-based
implementation without changing call sites.

* :func:`keyword_search` — SQLite ``LIKE`` based keyword retrieval. It
  splits the query into keywords (whitespace tokens plus individual CJK
  characters), filters chunks whose ``keyword_text``/``text`` match any
  keyword, scores by weighted occurrence count (title 3x, filename 2x,
  body 1x), and returns the top-K.
* :func:`vector_search` — reserved for Task 11; raises
  ``NotImplementedError``.
* :func:`merge_and_deduplicate` — de-duplicates keyword + vector
  results by ``chunk_id``.
* :func:`rerank` — placeholder re-ranker that preserves the keyword
  score ordering.
"""
from __future__ import annotations

import re
from typing import List

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.material import Material
from app.models.material_chunk import MaterialChunk

# CJK Unified Ideographs range; used to also split Chinese queries into
# single-character keywords so multi-char terms like "快表" can still
# match chunks that only contain "表".
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

# Common Chinese stop characters that produce too many false positives
# if used as individual LIKE keywords. Ported from
# concept_graph_service.CJK_STOP_CHARS (audit Task 6, commit 1388e91).
_CJK_STOP_CHARS = set("的是了和与及在为对中上下一种一个可以通过")


def _split_keywords(query: str) -> List[str]:
    """Split ``query`` into keywords for retrieval.

    Three extraction strategies ensure both Chinese and English queries
    produce useful search terms:

    1. **Whitespace tokens** — kept as-is (handles English queries like
       "TCP protocol header").
    2. **ASCII words (>= 2 chars)** — extracted via regex so terms like
       "TCP", "UDP", "IP" inside Chinese queries ("什么是TCP协议？")
       become searchable keywords. Without this, "TCP" is trapped inside
       the unsplit CJK string and never matches.
    3. **CJK 2-grams** — bigrams of non-stop CJK characters, so "协议"
       becomes a keyword instead of single chars "协"/"议" which match
       too broadly. Single CJK chars are only used when the query is too
       short to form any bigram (e.g., a single-character query).

    All keywords are lowercased and de-duplicated (order-preserving).
    """
    if not query or not query.strip():
        return []

    # 1. Whitespace tokens
    tokens = [t for t in query.split() if t]

    # 2. ASCII words >= 2 characters (e.g. "TCP", "UDP", "HTTP")
    ascii_words = re.findall(r"[a-zA-Z]{2,}", query)

    # 3. CJK 2-grams from non-stop chars (e.g. "协议" from "什么是TCP协议？")
    cjk_chars = [
        c for c in _CJK_PATTERN.findall(query)
        if c not in _CJK_STOP_CHARS
    ]
    cjk_grams: list[str] = []
    for i in range(len(cjk_chars) - 1):
        gram = cjk_chars[i] + cjk_chars[i + 1]
        cjk_grams.append(gram)
    # Only keep single non-stop CJK chars when no bigrams could be
    # formed (i.e., the query is a single CJK character).  When bigrams
    # exist, the individual chars produce too many false positives
    # (e.g., searching "信道" would match "通信" via the single char
    # "信", or "道路" via "道").
    if not cjk_grams:
        cjk_grams.extend(cjk_chars)

    seen: set[str] = set()
    keywords: List[str] = []
    for kw in tokens + ascii_words + cjk_grams:
        kw_lower = kw.lower()
        if kw_lower and kw_lower not in seen:
            seen.add(kw_lower)
            keywords.append(kw_lower)
    return keywords


def keyword_search(
    db: Session, course_id: int, query: str, top_k: int = 12
) -> list[dict]:
    """Keyword retrieval over a course's parsed chunks.

    Uses SQLite ``LIKE`` on ``material_chunks.keyword_text`` and
    ``material_chunks.text`` to find chunks that match any keyword
    derived from ``query``. Only chunks whose parent material has
    ``status='ready'`` are considered so partially-parsed materials
    never surface in search results.

    Scoring applies title/filename weighting: a keyword hit in the
    chunk title counts 3x, in the material filename 2x, and in the
    body text 1x. This prioritises chunks whose heading or source
    filename directly matches the query.

    Args:
        db: SQLAlchemy session.
        course_id: Course to scope the search to.
        query: Free-form query string. Whitespace tokens become
            keywords; CJK characters in the query are also added
            individually. An empty/whitespace query returns ``[]``.
        top_k: Maximum number of results to return.

    Returns:
        A list of dicts sorted by descending ``score`` with keys:
        ``chunk_id``, ``text``, ``score``, ``page_no``, ``material_id``,
        ``filename``, ``title``.
    """
    keywords = _split_keywords(query)
    if not keywords:
        return []

    like_conditions = []
    for kw in keywords:
        pattern = f"%{kw}%"
        like_conditions.append(MaterialChunk.keyword_text.like(pattern))
        like_conditions.append(MaterialChunk.text.like(pattern))

    rows = (
        db.query(MaterialChunk, Material.filename)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(
            MaterialChunk.course_id == course_id,
            Material.status == "ready",
            or_(*like_conditions),
        )
        .all()
    )

    results: list[dict] = []
    for chunk, filename in rows:
        text = chunk.text or ""
        text_lower = text.lower()
        title_lower = (chunk.title or "").lower()
        filename_lower = (filename or "").lower()

        # --- Density-based scoring ---
        # Count how many distinct keywords match (coverage) and total hits.
        match_count = 0  # number of distinct keywords that matched
        raw_score = 0
        for kw in keywords:
            kw_l = kw.lower()
            title_hits = title_lower.count(kw_l)
            fname_hits = filename_lower.count(kw_l)
            text_hits = text_lower.count(kw_l)
            total_hits = title_hits + fname_hits + text_hits
            if total_hits > 0:
                match_count += 1
            raw_score += title_hits * 3 + fname_hits * 2 + text_hits

        if raw_score <= 0:
            continue

        # Density: keyword hits per 100 characters of text.
        # A chunk with 5 hits in 200 chars is far more relevant than
        # 5 hits in 2000 chars (where "信道" may only appear tangentially).
        text_len = max(len(text), 1)
        density = raw_score / (text_len / 100)

        # Coverage bonus: matching more distinct keywords means the chunk
        # is broadly about the topic, not just mentioning it once.
        coverage_bonus = match_count / max(len(keywords), 1)

        # Title match bonus: a chunk whose title contains the keyword
        # is more relevant than one where only the body matches.
        has_title_match = any(
            kw.lower() in title_lower for kw in keywords
        )
        title_bonus = 0.15 if has_title_match else 0.0

        # Final normalized score (0-1 range for the API).
        # density typically ranges 0.5-30 for relevant chunks.
        # Coefficients are tuned so title_bonus (0.15) creates a
        # clear separation between title-matching and body-only chunks,
        # even for short texts where density is naturally high.
        normalized_score = min(
            1.0, (density * 0.02) + (coverage_bonus * 0.2) + title_bonus
        )

        # Minimum relevance threshold: chunk must either have density > 0.5
        # (at least ~1 hit per 200 chars) or have a title match.
        if density < 0.5 and not has_title_match:
            continue

        results.append(
            {
                "chunk_id": chunk.id,
                "text": text,
                "score": round(normalized_score, 4),
                "page_no": chunk.page_no,
                "material_id": chunk.material_id,
                "filename": filename,
                "title": chunk.title,
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)

    # Deduplicate: keep only the highest-scoring chunk per (material_id, page_no)
    results = _deduplicate_results(results)

    # Generate snippets for each result
    for r in results:
        r["snippet"] = generate_snippet(r["text"], keywords)

    return results[:top_k]


def _deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate results from the same (filename, page_no).

    When multiple chunks from the same page match, keep only the
    highest-scoring one to avoid redundant results. Uses filename
    instead of material_id so that the same PDF uploaded as different
    material records is still deduplicated. When page_no is None
    (non-PDF materials), each chunk is treated as unique.
    """
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in results:
        page_no = r.get("page_no")
        filename = r.get("filename", "")
        if page_no is None:
            # Non-PDF chunks: treat each as unique
            key = ("__none__", r.get("chunk_id"))
        else:
            key = (filename, page_no)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def generate_snippet(
    text: str, keywords: list[str], max_len: int = 150
) -> str:
    """Extract a context snippet around the first keyword match.

    Filters out noise lines (IP addresses, page numbers, single letters,
    OCR artifacts) and returns a clean snippet centered on the keyword.
    """
    if not text:
        return ""

    # Clean OCR/PPT noise symbols from the full text first
    _OCR_SYMBOLS = re.compile(r"[◆◇■►●○▪▫▶▷★☆▼▽▲△◼➢➣➤➔➧]")
    _YEAR_CHAPTER = re.compile(r"\b\d{4}\s+(?:Chapter|Spring|Fall|Autumn|Summer)\d*\b", re.IGNORECASE)
    _BRACKET_REF = re.compile(r"\[[A-Za-z]+\]")
    cleaned_text = _OCR_SYMBOLS.sub("", text)
    cleaned_text = _YEAR_CHAPTER.sub("", cleaned_text)
    cleaned_text = _BRACKET_REF.sub("", cleaned_text)

    lines = [l.strip() for l in cleaned_text.split("\n") if l.strip()]
    # Filter noise lines: pure numbers/dots, page refs, single-letter patterns
    _NOISE_LINE = re.compile(
        r"^[\d\s\.\-:]+$"  # pure numbers/dots (IP, page numbers)
        r"|^[A-Z]\s+[A-Z]\s"  # diagram labels like "A YX B Z"
        r"|^第\d+页"
        r"|^P\d+"
        r"|^\d{4}\s*$"  # standalone year
    )
    clean_lines = [
        l for l in lines if not _NOISE_LINE.match(l) and len(l) >= 3
    ]
    if not clean_lines:
        return cleaned_text[:max_len]

    # Find the first line containing a keyword
    kw_lower = [k.lower() for k in keywords]
    match_idx = 0
    for i, line in enumerate(clean_lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in kw_lower):
            match_idx = i
            break

    # Take 1 line before and 2 lines after the match for context
    start = max(0, match_idx - 1)
    end = min(len(clean_lines), match_idx + 3)
    snippet = " ".join(clean_lines[start:end])
    # Normalize whitespace
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) > max_len:
        # Center on the first keyword
        kw_pos = -1
        snippet_lower = snippet.lower()
        for kw in kw_lower:
            pos = snippet_lower.find(kw)
            if pos >= 0:
                kw_pos = pos
                break
        if kw_pos >= 0:
            half = max_len // 2
            start_pos = max(0, kw_pos - half)
            snippet = snippet[start_pos:start_pos + max_len]
        else:
            snippet = snippet[:max_len]
    return snippet.strip()


def vector_search(
    db: Session, course_id: int, query: str, top_k: int = 12
) -> list[dict]:
    """Vector recall over a course's chunks.

    Reserved for Task 11. The eventual implementation will embed the
    query, compare against chunk embeddings stored via
    ``MaterialChunk.embedding_id``, and return the top-K nearest
    neighbours using cosine similarity.

    Returns the same dict shape as :func:`keyword_search`.
    """
    raise NotImplementedError("vector_search will be implemented in Task 11")


def merge_and_deduplicate(
    chunks_kw: list[dict], chunks_vec: list[dict]
) -> list[dict]:
    """Merge keyword and vector result lists, de-duplicating by ``chunk_id``.

    Keyword hits come first (preserving their order), then vector-only
    hits are appended. The first occurrence of each ``chunk_id`` wins
    so a chunk that appears in both lists keeps its keyword-side score.
    """
    seen: set = set()
    merged: list[dict] = []
    for chunk in list(chunks_kw) + list(chunks_vec):
        cid = chunk.get("chunk_id")
        if cid in seen:
            continue
        seen.add(cid)
        merged.append(chunk)
    return merged


def rerank(question: str, candidates: list[dict], top_k: int = 12) -> list[dict]:
    """Re-rank merged candidates by relevance to ``question``.

    Reserved for Task 11. The placeholder simply sorts by the existing
    ``score`` field (produced by keyword search) in descending order
    and truncates to ``top_k``. The real implementation will use a
    cross-encoder or LLM-based reranker.
    """
    ranked = sorted(
        candidates, key=lambda item: item.get("score", 0), reverse=True
    )
    return ranked[:top_k]


__all__ = [
    "keyword_search",
    "vector_search",
    "merge_and_deduplicate",
    "rerank",
]
