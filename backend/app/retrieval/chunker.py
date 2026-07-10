"""Text chunking strategies for material content.

The chunker takes the text extracted by :mod:`app.retrieval.parsers`
and splits it into retrieval-sized pieces. The default target length
is 600 characters with a 100-character overlap, which keeps each chunk
within the 500-800 range requested by the design while preserving
context across chunk boundaries.

Two entry points are provided:

* :func:`chunk_text` operates on a single string and is the building block.
* :func:`build_chunks` takes the ``[(page_no, text), ...]`` list produced
  by ``parse_file`` and yields chunks that retain their originating
  page number, with globally sequential ``chunk_index`` values.

Heading detection (``第X章`` / ``X.`` / ``# `` / ``Chapter N``) is used
to prefer section boundaries; long sections without headings fall back
to length-based slicing with overlap.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

_HEADING_PATTERNS = [
    # 第一章 / 第2节 / 第三篇 ...
    re.compile(r"^第[一二三四五六七八九十百千零〇\d]+[章节篇部课]"),
    re.compile(r"^Chapter\s+\d+", re.IGNORECASE),
    # Markdown ATX headings: # / ## / ...
    re.compile(r"^#{1,6}\s+\S"),
    # "1. 引言" or "1.1 背景" (require a space + at least 2 chars to
    # avoid matching numbered sentences like "1.操作系统的...")
    re.compile(r"^\d+(\.\d+)*\.\s+\S{2,}"),
    re.compile(r"^\d+(\.\d+)*\s+\S{2,}"),
]

# Headings should be short; anything longer is almost certainly a body
# sentence that happens to start with a digit.
_MAX_HEADING_LEN = 80


def _is_heading(line: str) -> bool:
    """Return True if ``line`` looks like a section heading."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return False
    return any(pattern.match(stripped) for pattern in _HEADING_PATTERNS)


def _split_by_headings(text: str) -> List[Tuple[Optional[str], str]]:
    """Split text into (title, content) sections by heading lines.

    A heading line becomes the title of the section that follows it.
    Title-only sections (heading immediately followed by another heading)
    are merged into the next section to avoid empty/title-only chunks.
    """
    lines = text.splitlines(keepends=True)
    raw_sections: List[Tuple[Optional[str], str]] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        if _is_heading(line):
            if current_lines:
                raw_sections.append((current_title, "".join(current_lines)))
            current_title = line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        raw_sections.append((current_title, "".join(current_lines)))

    if not raw_sections:
        return [(None, text)]

    # Merge title-only sections into the next section.
    # A section is "title-only" when its content (minus the heading line
    # itself) is empty or whitespace — meaning the heading was immediately
    # followed by another heading.
    merged: List[Tuple[Optional[str], str]] = []
    pending_title: Optional[str] = None
    for title, content in raw_sections:
        body = content.strip()
        # Check if content is just the heading line itself
        if title and body == title:
            # Title-only section — defer to next section
            pending_title = title
            continue
        if pending_title is not None:
            # Prepend the deferred title to this section's content
            content = pending_title + "\n" + content
            title = pending_title
            pending_title = None
        merged.append((title, content))
    # If a title-only section was last, append it (shouldn't normally happen)
    if pending_title is not None:
        merged.append((pending_title, pending_title))

    return merged if merged else [(None, text)]


def _is_low_quality_chunk(text: str) -> bool:
    """Detect chunks that are likely extracted from diagrams/images.

    These chunks typically have:
    - High line repetition (same labels repeated)
    - Many very short lines (diagram labels like "R1", "H2")
    - Low vocabulary diversity
    """
    text = text.strip()
    if not text:
        return True

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return True

    # Check line repetition: unique lines / total lines
    unique_ratio = len(set(lines)) / len(lines)
    if unique_ratio < 0.5:
        return True

    # Check short-line stacking: > 60% of lines are < 4 chars
    short_lines = sum(1 for l in lines if len(l) < 4)
    if len(lines) > 3 and short_lines / len(lines) > 0.6:
        return True

    # Check vocabulary diversity for longer chunks
    if len(text) > 50:
        # Simple CJK character-level diversity
        chars = [c for c in text if "\u4e00" <= c <= "\u9fff" or c.isalpha()]
        if chars:
            unique_chars = len(set(chars))
            if unique_chars / len(chars) < 0.3:
                return True

    return False


def chunk_text(
    text: str,
    chunk_size: int = 600,
    overlap: int = 100,
) -> List[dict]:
    """Split ``text`` into chunks of roughly ``chunk_size`` characters.

    Each chunk is a dict with ``text``, ``chunk_index``, ``title`` and
    ``page_no`` (always ``None`` here; :func:`build_chunks` fills it in).

    The splitter first segments the text by detected headings. Sections
    shorter than ``chunk_size`` become a single chunk; longer sections
    are sliced with a sliding window of step ``chunk_size - overlap``
    so consecutive chunks overlap by ``overlap`` characters.

    Chunks detected as low-quality (diagram text, repetitive labels)
    are skipped so they never enter the retrieval store.
    """
    if not text or not text.strip():
        return []

    sections = _split_by_headings(text)
    step = max(1, chunk_size - overlap)

    chunks: List[dict] = []
    chunk_index = 0
    for title, content in sections:
        content = content.strip()
        if not content:
            continue
        if len(content) <= chunk_size:
            if _is_low_quality_chunk(content):
                continue  # Skip low-quality chunks (diagram text, repetitive labels)
            chunks.append(
                {
                    "text": content,
                    "chunk_index": chunk_index,
                    "title": title,
                    "page_no": None,
                }
            )
            chunk_index += 1
            continue

        start = 0
        content_len = len(content)
        while start < content_len:
            piece = content[start : start + chunk_size]
            start += step
            if _is_low_quality_chunk(piece):
                continue  # Skip low-quality chunks (diagram text, repetitive labels)
            chunks.append(
                {
                    "text": piece,
                    "chunk_index": chunk_index,
                    "title": title,
                    "page_no": None,
                }
            )
            chunk_index += 1
    return chunks


def build_chunks(
    pages: List[Tuple[Optional[int], str]],
    chunk_size: int = 600,
    overlap: int = 100,
) -> List[dict]:
    """Build chunks from parsed pages, preserving ``page_no``.

    Args:
        pages: ``[(page_no, text), ...]`` as returned by ``parse_file``.
            ``page_no`` may be ``None`` for non-paginated formats.
        chunk_size: target chunk size in characters.
        overlap: overlap between adjacent chunks within a page.

    Returns:
        List of chunk dicts with globally sequential ``chunk_index``
        and ``page_no`` propagated from the originating page.
    """
    all_chunks: List[dict] = []
    chunk_index = 0
    for page_no, text in pages:
        page_chunks = chunk_text(
            text, chunk_size=chunk_size, overlap=overlap
        )
        for chunk in page_chunks:
            chunk["page_no"] = page_no
            chunk["chunk_index"] = chunk_index
            chunk_index += 1
            all_chunks.append(chunk)
    return all_chunks


def clean_keyword_text(text: str) -> str:
    """Normalise text for keyword-based retrieval.

    Collapses runs of whitespace (including newlines and tabs) into a
    single space and strips leading/trailing whitespace. The original
    wording is preserved so keyword matching still works.
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()
