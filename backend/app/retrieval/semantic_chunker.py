"""V6 Semantic Chunker — replaces fixed character-window splitting.

Split priority (high to low):
1. Chapter/section heading boundary
2. Paragraph boundary (between body blocks)
3. List as whole (all list items with same heading stay together)
4. Table as whole (all table blocks stay together)
5. Sentence boundary (Chinese 。！？ and English .!?)
6. Hard length limit fallback (records split_reason=hard_limit_fallback)

Protected terms (never split across chunk boundaries):
TCP/IP, CSMA/CD, HTTP/2, B+树, I/O, Client/Server
"""
from __future__ import annotations

import re
from typing import List

from app.retrieval.document_ir import DocumentBlock, DocumentPage

CHUNKER_VERSION = "semantic-v7"

# Terms that must never be split across a chunk boundary.
_PROTECTED_TERMS = [
    "TCP/IP", "CSMA/CD", "HTTP/2", "B+树", "I/O", "Client/Server",
]

# Sentence-ending punctuation (Chinese + English).
_SENTENCE_END = set("。！？.!?")

# Heading block types that trigger a new chunk.
_HEADING_TYPES = {"heading", "title"}


def _is_heading(block: DocumentBlock) -> bool:
    return block.block_type in _HEADING_TYPES


def _is_list(block: DocumentBlock) -> bool:
    return block.block_type == "list"


def _is_table(block: DocumentBlock) -> bool:
    return block.block_type == "table"


def _is_protected_at_boundary(end_text: str, start_text: str) -> bool:
    """Check if a protected term is split between end of one chunk and start of next."""
    for term in _PROTECTED_TERMS:
        for split_pos in range(1, len(term)):
            suffix = term[-split_pos:]
            prefix = term[:-split_pos]
            if end_text.endswith(suffix) and start_text.startswith(prefix):
                return True
    return False


def _find_safe_split_point(text: str, max_length: int, min_pos: int = 0) -> tuple[int, str]:
    """Find the best split point in *text* that doesn't exceed *max_length*.

    Returns (split_pos, split_reason). Tries sentence boundaries first,
    then falls back to hard limit. Only searches positions >= min_pos
    to avoid splitting at heading/body separators.
    """
    if len(text) <= max_length:
        return len(text), "paragraph"

    search_end = min(len(text), max_length)

    # Try sentence boundaries first (search backward from max_length)
    for i in range(search_end, min_pos, -1):
        if i <= 0 or i > len(text):
            continue
        if text[i - 1] in _SENTENCE_END:
            end_part = text[:i]
            start_part = text[i:]
            if not _is_protected_at_boundary(end_part, start_part):
                return i, "sentence"

    # Try double-newline (paragraph boundary)
    for i in range(search_end, min_pos + 1, -1):
        if i <= 0 or i >= len(text):
            continue
        if text[i - 1] == '\n' and text[i] == '\n':
            end_part = text[:i]
            start_part = text[i:]
            if not _is_protected_at_boundary(end_part, start_part):
                return i, "paragraph"

    # Try single newline (but only after min_pos to avoid heading separators)
    for i in range(search_end, min_pos + 1, -1):
        if i <= 0 or i >= len(text):
            continue
        if text[i - 1] == '\n':
            end_part = text[:i]
            start_part = text[i:]
            if not _is_protected_at_boundary(end_part, start_part):
                return i, "paragraph"

    # Try space boundary (word boundary)
    for i in range(search_end, min_pos, -1):
        if i <= 0 or i >= len(text):
            continue
        if text[i - 1] == ' ':
            end_part = text[:i]
            start_part = text[i:]
            if not _is_protected_at_boundary(end_part, start_part):
                return i, "sentence"

    # Check if splitting at max_length would break a protected term
    end_part = text[:max_length]
    start_part = text[max_length:]
    if _is_protected_at_boundary(end_part, start_part):
        for offset in range(1, min(20, max_length)):
            pos = max_length - offset
            if pos <= 0:
                break
            end_part = text[:pos]
            start_part = text[pos:]
            if not _is_protected_at_boundary(end_part, start_part):
                return pos, "hard_limit_fallback"
        return max_length, "hard_limit_fallback"

    return max_length, "hard_limit_fallback"


def _build_chunk(
    text: str,
    title: str,
    block_ids: list,
    page_nos: set,
    chunk_index: int,
    split_reason: str,
    fragments: list[dict] | None = None,
) -> dict:
    """Build a chunk dictionary.

    V7.4-02 P1-03: Fragment offsets are adjusted after stripping
    leading/trailing whitespace from text. The strip_offset and
    stripped_length are used to shift fragment offsets so they
    remain valid indices into the final chunk["text"].
    """
    page_nos_sorted = sorted(page_nos)
    # V7.4-02 P1-03: Track leading whitespace for offset adjustment
    strip_offset = len(text) - len(text.lstrip())
    stripped_text = text.strip()
    stripped_len = len(stripped_text)

    # Adjust fragment offsets to be relative to the stripped text
    adjusted_fragments = []
    if fragments:
        for frag in fragments:
            start = frag["text_start"] - strip_offset
            end = frag["text_end"] - strip_offset
            # Clamp to valid range
            start = max(0, min(start, stripped_len))
            end = max(0, min(end, stripped_len))
            if start < end:  # Only include non-empty fragments
                adjusted_fragments.append({
                    "block_id": frag["block_id"],
                    "text_start": start,
                    "text_end": end,
                })

    # V7.4-02 P1-04: Use dict.fromkeys to preserve insertion order
    # while deduplicating block IDs (set() loses order)
    ordered_block_ids = list(dict.fromkeys(block_ids))

    return {
        "text": stripped_text,
        "title": title,
        "page_start": page_nos_sorted[0] if page_nos_sorted else None,
        "page_end": page_nos_sorted[-1] if page_nos_sorted else None,
        "source_block_ids": ordered_block_ids,
        "source_fragments_json": adjusted_fragments,
        "split_reason": split_reason,
        "chunk_index": chunk_index,
        "chunker_version": CHUNKER_VERSION,
    }


def _split_fragments(fragments: list[dict], split_pos: int) -> tuple[list[dict], list[dict]]:
    """Divide fragment ranges at *split_pos*.

    Returns (first_part_fragments, second_part_fragments) where each
    fragment's text_start/text_end are adjusted to be relative to the
    respective part's text.
    """
    first: list[dict] = []
    second: list[dict] = []
    for frag in fragments:
        start = frag["text_start"]
        end = frag["text_end"]
        if start < split_pos:
            first.append({
                "block_id": frag["block_id"],
                "text_start": start,
                "text_end": min(end, split_pos),
            })
        if end > split_pos:
            second.append({
                "block_id": frag["block_id"],
                "text_start": max(0, start - split_pos),
                "text_end": end - split_pos,
            })
    return first, second


def semantic_chunk(
    pages: List[DocumentPage],
    target_length: int = 600,
    max_length: int = 1000,
) -> List[dict]:
    """Split document pages into semantic chunks.

    Args:
        pages: List of DocumentPage objects with ordered DocumentBlock items.
        target_length: Target character length per chunk.
        max_length: Maximum character length before forced split.

    Returns:
        List of chunk dictionaries with text, title, page_start, page_end,
        source_block_ids, split_reason, chunk_index, chunker_version.
    """
    if not pages:
        return []

    chunks: list[dict] = []
    chunk_index = 0

    # Current chunk accumulator
    current_text = ""
    current_title = ""
    current_block_ids: list[str] = []
    current_page_nos: set = set()
    current_fragments: list[dict] = []

    def _flush(reason: str = "paragraph"):
        nonlocal current_text, current_title, current_block_ids, current_page_nos, current_fragments, chunk_index
        if current_text.strip() and current_block_ids:
            chunks.append(
                _build_chunk(
                    current_text,
                    current_title,
                    current_block_ids,
                    current_page_nos,
                    chunk_index,
                    reason,
                    current_fragments,
                )
            )
            chunk_index += 1
        current_text = ""
        current_title = ""
        current_block_ids = []
        current_page_nos = set()
        current_fragments = []

    for page in pages:
        page_no = page.page_no
        blocks = page.blocks
        i = 0
        while i < len(blocks):
            block = blocks[i]

            # Heading → flush current, start new chunk with heading
            if _is_heading(block):
                _flush("heading")
                current_title = block.text
                current_text = block.text + "\n"
                current_block_ids = [block.block_id]
                current_page_nos = {page_no}
                current_fragments = [{"block_id": block.block_id, "text_start": 0, "text_end": len(current_text)}]
                i += 1
                continue

            # List → collect all consecutive list blocks, keep together
            if _is_list(block):
                # Flush if current text is getting large
                if len(current_text) + 200 > max_length and current_text.strip():
                    _flush("paragraph")

                while i < len(blocks) and _is_list(blocks[i]):
                    b = blocks[i]
                    item_text = b.text + "\n"
                    # If the single list block itself exceeds max_length,
                    # split it at newline boundaries
                    if len(item_text) > max_length:
                        # Flush current content first
                        if current_text.strip():
                            _flush("list")
                        # Split the list block text at newline boundaries
                        lines = b.text.split("\n")
                        for line in lines:
                            if not line.strip():
                                continue
                            if len(current_text) + len(line) + 1 > max_length and current_text.strip():
                                _flush("list")
                            block_start = len(current_text)
                            current_text += line + "\n"
                            block_end = len(current_text)
                            current_block_ids.append(b.block_id)
                            current_page_nos.add(page_no)
                            current_fragments.append({"block_id": b.block_id, "text_start": block_start, "text_end": block_end})
                        i += 1
                        continue
                    # If adding this item exceeds max_length, flush and start new
                    if len(current_text) + len(item_text) > max_length and current_text.strip():
                        _flush("list")
                    block_start = len(current_text)
                    current_text += item_text
                    block_end = len(current_text)
                    current_block_ids.append(b.block_id)
                    current_page_nos.add(page_no)
                    current_fragments.append({"block_id": b.block_id, "text_start": block_start, "text_end": block_end})
                    i += 1
                continue

            # Table → collect all consecutive table blocks, keep together
            if _is_table(block):
                table_text = ""
                table_ids = []
                table_start = len(current_text)
                while i < len(blocks) and _is_table(blocks[i]):
                    b = blocks[i]
                    item_start = table_start + len(table_text)
                    table_text += b.text + "\n"
                    item_end = table_start + len(table_text)
                    table_ids.append(b.block_id)
                    current_fragments.append({"block_id": b.block_id, "text_start": item_start, "text_end": item_end})
                    i += 1

                if len(current_text) + len(table_text) > max_length and current_text.strip():
                    _flush("table")

                current_text += table_text
                current_block_ids.extend(table_ids)
                current_page_nos.add(page_no)
                continue

            # Body block
            block_text = block.text

            # Check if adding this block would exceed max_length
            would_exceed_max = len(current_text) + len(block_text) + 1 > max_length
            current_exceeds_target = len(current_text) > target_length

            if would_exceed_max and current_text.strip():
                if current_exceeds_target:
                    # Current chunk is already over target — flush and start new
                    _flush("paragraph")
                    current_text = block_text + "\n"
                    current_block_ids = [block.block_id]
                    current_page_nos = {page_no}
                    current_fragments = [{"block_id": block.block_id, "text_start": 0, "text_end": len(current_text)}]
                else:
                    # Current text is under target but adding block exceeds max.
                    # Split the combined text at a safe point.
                    # Use heading length as min_pos to avoid splitting at heading/body separator
                    heading_len = len(current_title) + 1 if current_title else 0
                    min_pos = max(heading_len, 1)
                    combined = current_text + block_text + "\n"
                    split_pos, reason = _find_safe_split_point(combined, max_length, min_pos)
                    first_part = combined[:split_pos]
                    second_part = combined[split_pos:]

                    # Split fragments at the boundary
                    first_frags, second_frags = _split_fragments(current_fragments, split_pos)
                    # The new block's text is appended after current_text, so
                    # its fragment starts at len(current_text) and ends at len(combined).
                    new_block_start = len(current_text)
                    new_block_end = len(combined)
                    if new_block_start < split_pos:
                        first_frags.append({"block_id": block.block_id, "text_start": new_block_start, "text_end": min(new_block_end, split_pos)})
                    if new_block_end > split_pos:
                        second_frags.append({"block_id": block.block_id, "text_start": max(0, new_block_start - split_pos), "text_end": new_block_end - split_pos})

                    # Determine which block IDs are in each part
                    first_block_ids = list(dict.fromkeys(f["block_id"] for f in first_frags))
                    second_block_ids = list(dict.fromkeys(f["block_id"] for f in second_frags))

                    current_text = first_part
                    current_fragments = first_frags
                    current_block_ids = first_block_ids if first_block_ids else current_block_ids
                    _flush(reason)

                    current_text = second_part
                    current_block_ids = second_block_ids if second_block_ids else [block.block_id]
                    current_page_nos = {page_no}
                    current_fragments = second_frags
            elif current_exceeds_target and current_text.strip():
                # Current text exceeds target_length — split at this block boundary
                _flush("paragraph")
                current_text = block_text + "\n"
                current_block_ids = [block.block_id]
                current_page_nos = {page_no}
                current_fragments = [{"block_id": block.block_id, "text_start": 0, "text_end": len(current_text)}]
            else:
                # Add block to current chunk
                block_start = len(current_text)
                current_text += block_text + "\n"
                block_end = len(current_text)
                current_block_ids.append(block.block_id)
                current_page_nos.add(page_no)
                current_fragments.append({"block_id": block.block_id, "text_start": block_start, "text_end": block_end})

                # If current text exceeds target_length, check if we should
                # split at a sentence boundary. Only do this when there are
                # no more body blocks on this page (look-ahead) — otherwise
                # the block boundary will handle the split.
                if len(current_text) > target_length and len(current_text) <= max_length:
                    has_more_body = False
                    for j in range(i + 1, len(blocks)):
                        nxt = blocks[j]
                        if (not _is_heading(nxt) and not _is_list(nxt)
                                and not _is_table(nxt)):
                            has_more_body = True
                            break

                    if not has_more_body:
                        # Find the first sentence boundary after target_length
                        text_so_far = current_text
                        split_pos = -1
                        for j in range(target_length + 1, len(text_so_far)):
                            if text_so_far[j - 1] in _SENTENCE_END:
                                end_part = text_so_far[:j]
                                start_part = text_so_far[j:]
                                if (not _is_protected_at_boundary(end_part, start_part)
                                        and len(start_part.strip()) > 10):
                                    split_pos = j
                                    break

                        if split_pos > target_length:
                            first_part = text_so_far[:split_pos]
                            second_part = text_so_far[split_pos:]
                            first_frags, second_frags = _split_fragments(current_fragments, split_pos)
                            first_block_ids = list(dict.fromkeys(f["block_id"] for f in first_frags))
                            second_block_ids = list(dict.fromkeys(f["block_id"] for f in second_frags))
                            current_text = first_part
                            current_fragments = first_frags
                            current_block_ids = first_block_ids if first_block_ids else current_block_ids
                            _flush("sentence")
                            current_text = second_part
                            current_block_ids = second_block_ids if second_block_ids else current_block_ids
                            current_page_nos = {page_no}
                            current_fragments = second_frags

            i += 1

        # Between pages, check if we should split
        if len(current_text) > target_length:
            _flush("paragraph")

    # Flush remaining content
    if current_text.strip():
        _flush("paragraph")

    # Post-processing: verify no protected terms are split across boundaries
    for idx in range(len(chunks) - 1):
        end_text = chunks[idx]["text"]
        start_text = chunks[idx + 1]["text"]
        if _is_protected_at_boundary(end_text, start_text):
            merged_text = end_text + "\n" + start_text
            merged_ids = list(chunks[idx]["source_block_ids"]) + list(chunks[idx + 1]["source_block_ids"])
            merged_frags = list(chunks[idx].get("source_fragments_json", []))
            # Adjust second chunk's fragments to be relative to the merged text
            offset = len(end_text) + 1  # +1 for the newline
            for frag in chunks[idx + 1].get("source_fragments_json", []):
                merged_frags.append({
                    "block_id": frag["block_id"],
                    "text_start": frag["text_start"] + offset,
                    "text_end": frag["text_end"] + offset,
                })
            merged_pages = set()
            if chunks[idx]["page_start"]:
                for p in range(chunks[idx]["page_start"], chunks[idx]["page_end"] + 1):
                    merged_pages.add(p)
            if chunks[idx + 1]["page_start"]:
                for p in range(chunks[idx + 1]["page_start"], chunks[idx + 1]["page_end"] + 1):
                    merged_pages.add(p)
            merged_pages_sorted = sorted(merged_pages)
            chunks[idx] = {
                "text": merged_text.strip(),
                "title": chunks[idx]["title"] or chunks[idx + 1]["title"],
                "page_start": merged_pages_sorted[0] if merged_pages_sorted else None,
                "page_end": merged_pages_sorted[-1] if merged_pages_sorted else None,
                "source_block_ids": merged_ids,
                "source_fragments_json": merged_frags,
                "split_reason": "paragraph",
                "chunk_index": chunks[idx]["chunk_index"],
                "chunker_version": CHUNKER_VERSION,
            }
            del chunks[idx + 1]
            for j in range(len(chunks)):
                chunks[j]["chunk_index"] = j
            break

    return chunks


# Public production name.  Keep ``semantic_chunk`` for V6 callers and tests.
def semantic_chunk_document(
    pages: List[DocumentPage], *, config: dict | None = None,
    target_length: int | None = None, max_length: int | None = None,
) -> List[dict]:
    """Chunk a cleaned Document IR using the V7 production contract."""
    cfg = config or {}
    tl = target_length if target_length is not None else int(cfg.get("target_length", 600))
    ml = max_length if max_length is not None else int(cfg.get("max_length", 1000))
    return semantic_chunk(pages, target_length=tl, max_length=ml)
