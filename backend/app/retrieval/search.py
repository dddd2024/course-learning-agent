"""Retrieval strategies for the course learning assistant.

This module currently provides keyword-based search over
``material_chunks`` and reserves the interfaces for vector recall,
result merging, and re-ranking. The vector path is intentionally left
as a stub so downstream tasks (Task 11) can plug in an embedding-based
implementation without changing call sites.

* :func:`keyword_search` — SQLite ``LIKE`` based keyword retrieval. It
  splits the query into keywords (whitespace tokens plus individual CJK
  characters), filters chunks whose ``keyword_text``/``text`` match any
  keyword, scores by total occurrence count, and returns the top-K.
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


def _split_keywords(query: str) -> List[str]:
    """Split ``query`` into keywords for retrieval.

    Whitespace tokens are kept as-is. Individual CJK characters in the
    query are also added (deduplicated, order-preserving) so Chinese
    queries without spaces still produce useful keywords.
    """
    if not query or not query.strip():
        return []
    tokens = [t for t in query.split() if t]
    cjk_chars = _CJK_PATTERN.findall(query)
    seen: set[str] = set()
    keywords: List[str] = []
    for kw in tokens + cjk_chars:
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
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
        score = 0
        for kw in keywords:
            score += text_lower.count(kw.lower())
        if score <= 0:
            continue
        results.append(
            {
                "chunk_id": chunk.id,
                "text": text,
                "score": score,
                "page_no": chunk.page_no,
                "material_id": chunk.material_id,
                "filename": filename,
                "title": chunk.title,
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


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
