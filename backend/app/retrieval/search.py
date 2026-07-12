"""Retrieval strategies for the course learning assistant.

This module currently provides keyword-based search over
``material_chunks`` and reserves the interfaces for vector recall,
result merging, and re-ranking. The vector path is intentionally left
as a stub so downstream tasks (Task 11) can plug in an embedding-based
implementation without changing call sites.

* :func:`keyword_search` — SQLite ``LIKE`` based keyword retrieval. It
  splits the query into keywords (whitespace tokens plus individual CJK
  characters), filters chunks whose ``keyword_text``/``text`` match any
  keyword, scores by weighted occurrence count (title 2x, filename 2x,
  body 1x), and returns the top-K.
* :func:`vector_search` — reserved for Task 11; raises
  ``NotImplementedError``.
* :func:`merge_and_deduplicate` — de-duplicates keyword + vector
  results by ``chunk_id``.
* :func:`rerank` — placeholder re-ranker that preserves the keyword
  score ordering.
"""
from __future__ import annotations

import math
import re
from typing import List

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.retrieval.aliases import expand


def rebuild_fts_index(db: Session) -> None:
    """Rebuild the SQLite FTS5 index from active, indexable chunks."""
    db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS material_chunks_fts USING fts5(chunk_id UNINDEXED, course_id UNINDEXED, body, title)"))
    db.execute(text("DELETE FROM material_chunks_fts"))
    rows = db.query(MaterialChunk).filter(MaterialChunk.is_active == 1, MaterialChunk.is_indexable == 1).all()
    db.execute(text("INSERT INTO material_chunks_fts(chunk_id, course_id, body, title) VALUES (:chunk_id, :course_id, :body, :title)"), [{"chunk_id": row.id, "course_id": row.course_id, "body": row.text or "", "title": row.title or ""} for row in rows])
    db.commit()


def fts_search(db: Session, course_id: int, query: str, top_k: int = 12) -> list[dict]:
    """BM25 retrieval with alias expansion; return [] on unsupported SQLite."""
    terms = [term.replace('"', ' ') for value in expand(query) for term in _split_keywords(value)]
    if not terms:
        return []
    try:
        rebuild_fts_index(db)
        match = " OR ".join(dict.fromkeys(terms))
        rows = db.execute(text("SELECT chunk_id, bm25(material_chunks_fts) AS rank FROM material_chunks_fts WHERE material_chunks_fts MATCH :match AND course_id = :course_id ORDER BY rank LIMIT :limit"), {"match": match, "course_id": course_id, "limit": top_k}).mappings().all()
    except Exception:
        db.rollback()
        return []
    ids = [int(row["chunk_id"]) for row in rows]
    chunks = {row.id: row for row in db.query(MaterialChunk).filter(MaterialChunk.id.in_(ids)).all()}
    results = []
    lowered_terms = [term.lower() for term in terms]
    for cid, row in zip(ids, rows):
        if cid not in chunks:
            continue
        chunk = chunks[cid]
        title_bonus = 0.2 if any(term in (chunk.title or "").lower() for term in lowered_terms) else 0.0
        results.append({"chunk_id": cid, "text": chunk.text or "", "title": chunk.title, "page_no": chunk.page_no, "material_id": chunk.material_id, "filename": "", "score": round(1 / (1 + abs(float(row["rank"]))) + title_bonus, 4), "retrieval_mode": "fts_bm25"})
    return sorted(results, key=lambda item: item["score"], reverse=True)

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

    Scoring uses absolute hit count (title 2x, filename 2x, body 1x)
    combined with coverage (fraction of distinct keywords matched) and
    a logarithmic length bonus. Title-only chunks -- where text is very
    short and consists mostly of the heading -- are filtered out so
    they do not crowd out chunks with actual explanatory content.

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
    fts_results = fts_search(db, course_id, query, top_k=top_k)
    if fts_results:
        for item in fts_results:
            item["snippet"] = generate_snippet(item["text"], _split_keywords(query))
        return fts_results
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
            MaterialChunk.is_indexable == 1,
            MaterialChunk.is_active == 1,
            Material.status == "ready",
            or_(*like_conditions),
        )
        .all()
    )

    results: list[dict] = []
    # Pre-compile word-boundary patterns for ASCII keywords
    # CJK keywords use substring matching (no word boundaries in Chinese)
    ascii_kws = [kw for kw in keywords if re.match(r"^[a-z]{2,}$", kw)]
    cjk_kws = [kw for kw in keywords if kw not in ascii_kws]
    ascii_patterns = {
        kw: re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        for kw in ascii_kws
    }

    for chunk, filename in rows:
        text = chunk.text or ""
        text_lower = text.lower()
        title_lower = (chunk.title or "").lower()
        filename_lower = (filename or "").lower()

        # --- Scoring: absolute hits + coverage, demote title-only chunks ---
        # Track hits by location so we can detect and filter title-only
        # chunks that lack real body content.
        match_count = 0  # number of distinct keywords that matched
        raw_score = 0
        total_title_hits = 0
        total_fname_hits = 0
        total_text_hits = 0
        for kw in keywords:
            if kw in ascii_patterns:
                pat = ascii_patterns[kw]
                title_hits = len(pat.findall(chunk.title or ""))
                fname_hits = len(pat.findall(filename or ""))
                text_hits = len(pat.findall(text))
            else:
                kw_l = kw.lower()
                title_hits = title_lower.count(kw_l)
                fname_hits = filename_lower.count(kw_l)
                text_hits = text_lower.count(kw_l)
            total_hits = title_hits + fname_hits + text_hits
            if total_hits > 0:
                match_count += 1
            raw_score += title_hits * 2 + fname_hits * 2 + text_hits
            total_title_hits += title_hits
            total_fname_hits += fname_hits
            total_text_hits += text_hits

        if raw_score <= 0:
            continue

        # Filter: if there are ASCII keywords, at least one must match
        # as a whole word. This prevents "NAT" from matching "International".
        if ascii_kws:
            ascii_word_match = any(
                ascii_patterns[kw].search(text)
                or ascii_patterns[kw].search(chunk.title or "")
                or ascii_patterns[kw].search(filename or "")
                for kw in ascii_kws
            )
            if not ascii_word_match:
                continue

        # Text length for reference
        text_len = max(len(text), 1)

        # Filter: chunks with no body text hits and short text are likely
        # title/filename-only matches with no explanatory content.
        if total_text_hits <= 0 and text_len < 50:
            continue

        # Detect title-only chunks: text is very short and consists mostly
        # of the title (very little content beyond the heading line).
        # These chunks provide no explanatory value — skip them entirely.
        # The threshold of 5 chars ensures we only filter chunks where the
        # body is essentially empty, not chunks with short but real content.
        if text_len < 50 and title_lower:
            text_without_title = text_lower.replace(
                title_lower, ""
            ).strip()
            if len(text_without_title) < 5:
                continue

        # Coverage: fraction of distinct keywords that matched
        coverage = match_count / max(len(keywords), 1)

        # Absolute hit score: total keyword hits weighted by location
        # (title 2x, filename 2x, body 1x). This replaces density-based
        # scoring which inflated short chunks: a 10-char title with 2 hits
        # had density=60 (capped to 1.0), while a 600-char body with 3
        # hits had density=0.5 and was barely retained.
        hit_score = raw_score

        # Length bonus: longer chunks tend to contain more useful context.
        # Logarithmic scale so a 600-char chunk gets ~2x bonus over 10-char.
        length_bonus = min(0.3, math.log10(max(text_len, 1)) * 0.1)

        # Title match bonus (kept small to avoid title-only inflation)
        title_bonus = 0.05 if total_title_hits > 0 else 0.0

        # Final normalized score (0-1 range)
        normalized_score = min(
            1.0,
            (hit_score * 0.05)
            + (coverage * 0.3)
            + length_bonus
            + title_bonus
        )

        if normalized_score <= 0:
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
                "retrieval_mode": "keyword_fallback",
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)

    # Deduplicate only truly repeated source text; different chunks on the
    # same page are separate evidence and must remain retrievable.
    # by text similarity (see _deduplicate_results).
    results = _deduplicate_results(results)

    # Generate snippets for each result
    for r in results:
        r["snippet"] = generate_snippet(r["text"], keywords)

    return results[:top_k]


def _text_overlap_ratio(a: str, b: str) -> float:
    """Calculate character-level overlap ratio between two strings.

    Uses the Jaccard similarity of 2-gram (bigram) sets so that short
    prefixes can be compared robustly without requiring exact equality.
    Returns a value in ``[0.0, 1.0]`` where ``1.0`` means the two
    strings share all their 2-grams.
    """
    if not a or not b:
        return 0.0
    a_grams = {a[i:i + 2] for i in range(len(a) - 1)}
    b_grams = {b[i:i + 2] for i in range(len(b) - 1)}
    if not a_grams or not b_grams:
        return 0.0
    return len(a_grams & b_grams) / len(a_grams | b_grams)


def _deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate results.

    Three dedup strategies are applied in order:

    1. **Exact duplicate content** — only identical chunks from the same
       material version are collapsed.
    2. **page_no is None (docx/txt/md)** — there is no page to key on,
       so dedup by text similarity: if the first 100 characters of two
       chunks overlap by >= 60%, treat them as duplicates and keep the
       higher-scoring one. This replaces the old behaviour where every
       ``page_no is None`` chunk was treated as unique (no dedup at all).
    3. **Cross-page** — near-identical content repeated across different
       pages (headers, chapter dividers, repeated slide text) is deduped
       using an 80% text overlap threshold so only the highest-scoring
       copy is kept.

    Similarity checks are scoped by ``material_id`` rather than filenames;
    two users can upload unrelated documents with the same filename.
    """
    # (filename, text_prefix, score, chunk_id) for every chunk currently
    # held in ``deduped``; used for the text-similarity strategies (2 & 3).
    seen_texts: list[tuple[str, str, float, int]] = []
    deduped: list[dict] = []

    for r in results:
        page_no = r.get("page_no")
        material_id = r.get("material_id")
        text = r.get("text", "")
        score = r.get("score", 0)
        chunk_id = r.get("chunk_id")

        # Strategy 2 & 3: text-similarity dedup, scoped to the same file
        # (filename). This mirrors the original filename-based keying so
        # that the same document uploaded under different material
        # records is still deduplicated, while genuinely different source
        # files (e.g. two .txt notes) remain distinct and filename
        # weighting stays observable. Within a single file, page_no is
        # None chunks overlap >= 60% (strategy 2) and cross-page chunks
        # overlap >= 80% (strategy 3) are collapsed to the higher score.
        text_prefix = text[:100].strip()
        threshold = 0.6 if page_no is None else 0.8
        action = "keep"  # one of: keep | replace | drop
        for i, (ex_filename, ex_prefix, ex_score, ex_id) in enumerate(
            seen_texts
        ):
            if ex_filename != material_id:
                continue
            if not text_prefix or not ex_prefix:
                continue
            overlap = _text_overlap_ratio(text_prefix, ex_prefix)
            if overlap >= threshold:
                if score > ex_score:
                    # Replace the existing representative with the
                    # higher-scoring chunk (defensive: results is
                    # pre-sorted desc, so this branch rarely triggers).
                    action = "replace"
                    seen_texts[i] = (material_id, text_prefix, score, chunk_id)
                    deduped = [
                        d for d in deduped
                        if d.get("chunk_id") != ex_id
                    ]
                else:
                    action = "drop"
                break

        if action == "drop":
            continue

        # r is retained — either as a new entry or as a replacement.
        if action == "keep":
            seen_texts.append((material_id, text_prefix, score, chunk_id))
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
