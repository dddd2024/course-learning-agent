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


def _split_long_line(line: str, max_length: int) -> list[str]:
    """Split a single line that exceeds *max_length* into smaller pieces.

    Split priority (same as :func:`_find_safe_split_point`):
    1. Sentence boundary (Chinese 。！？ and English .!?)
    2. Space boundary (word boundary)
    3. Hard limit (max_length), adjusted to avoid breaking protected terms

    Each returned piece is guaranteed to be <= max_length.
    """
    pieces: list[str] = []
    remaining = line
    while len(remaining) > max_length:
        search_end = min(len(remaining), max_length)
        split_pos = -1

        # 1. Sentence boundary (search backward from max_length)
        for i in range(search_end, 0, -1):
            if remaining[i - 1] in _SENTENCE_END:
                end_part = remaining[:i]
                start_part = remaining[i:]
                if not _is_protected_at_boundary(end_part, start_part):
                    split_pos = i
                    break

        # 2. Space boundary
        if split_pos == -1:
            for i in range(search_end, 0, -1):
                if remaining[i - 1] == ' ':
                    end_part = remaining[:i]
                    start_part = remaining[i:]
                    if not _is_protected_at_boundary(end_part, start_part):
                        split_pos = i
                        break

        # 3. Hard limit (avoid breaking a protected term if possible)
        if split_pos == -1:
            end_part = remaining[:max_length]
            start_part = remaining[max_length:]
            if _is_protected_at_boundary(end_part, start_part):
                for offset in range(1, min(20, max_length)):
                    pos = max_length - offset
                    if pos <= 0:
                        break
                    end_part = remaining[:pos]
                    start_part = remaining[pos:]
                    if not _is_protected_at_boundary(end_part, start_part):
                        split_pos = pos
                        break
            if split_pos == -1:
                split_pos = max_length

        pieces.append(remaining[:split_pos])
        remaining = remaining[split_pos:]

    if remaining:
        pieces.append(remaining)
    return pieces


def _split_table_text(table_text: str, max_length: int) -> list[str]:
    """Split table text into pieces each <= *max_length*.

    Splits at row (newline) boundaries, repeating the header row (the
    first non-empty line) in every continuation chunk.  If a single row
    itself exceeds *max_length* it is further split via
    :func:`_split_long_line`.  When the header row alone exceeds
    *max_length* the entire table is treated as one long line.
    """
    lines = table_text.split("\n")
    # Drop trailing empty lines produced by the trailing "\n".
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []

    header = lines[0]
    # Header row alone exceeds the limit — treat the whole table as a
    # single long line and split without header repetition.
    if len(header) > max_length:
        return _split_long_line(table_text.strip(), max_length)

    header_prefix = header + "\n"
    data_lines = lines[1:]

    chunks: list[str] = []
    current = header_prefix  # first chunk always starts with the header

    for line in data_lines:
        if not line.strip():
            continue
        # A single row that itself exceeds max_length must be sub-split.
        if len(line) > max_length:
            if current.strip():
                chunks.append(current.rstrip("\n"))
                current = ""
            for sub in _split_long_line(line, max_length):
                if not current:
                    current = header_prefix
                if len(current) + len(sub) + 1 > max_length and current.strip():
                    chunks.append(current.rstrip("\n"))
                    current = header_prefix
                current += sub + "\n"
        else:
            if not current:
                current = header_prefix
            if len(current) + len(line) + 1 > max_length and current.strip():
                chunks.append(current.rstrip("\n"))
                current = header_prefix
            current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip("\n"))

    return chunks


def _make_fragment(
    block_id: str,
    page_no: int,
    source_start: int,
    source_end: int,
    text_start: int,
    text_end: int,
    kind: str = "source",
) -> dict:
    """Create a fragment dict with all 7 required fields.

    Required fields: block_id, page_no, source_start, source_end,
    text_start, text_end, kind.
    kind must be "source" or "repeated_header".
    """
    return {
        "block_id": block_id,
        "page_no": page_no,
        "source_start": source_start,
        "source_end": source_end,
        "text_start": text_start,
        "text_end": text_end,
        "kind": kind,
    }


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

    V7.4.2-01: Fragments preserve all 7 required fields:
    block_id, page_no, source_start, source_end, text_start, text_end, kind.
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
            original_start = frag["text_start"]
            original_end = frag["text_end"]
            start = original_start - strip_offset
            end = original_end - strip_offset
            # Clamp to valid range
            start = max(0, min(start, stripped_len))
            end = max(0, min(end, stripped_len))
            if start < end:  # Only include non-empty fragments
                # Stripping only removes characters at the two boundaries.
                # Fragments represent source slices, so trim their source
                # offsets by exactly the same amount (never proportionally).
                left_trim = max(0, strip_offset - original_start)
                right_trim = max(0, original_end - (strip_offset + stripped_len))
                adjusted_fragments.append({
                    "block_id": frag["block_id"],
                    "page_no": frag.get("page_no", 0),
                    "source_start": frag.get("source_start", 0) + left_trim,
                    "source_end": frag.get("source_end", frag.get("text_end", end) - frag.get("text_start", 0) + frag.get("source_start", 0)) - right_trim,
                    "text_start": start,
                    "text_end": end,
                    "kind": frag.get("kind", "source"),
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
    respective part's text.  Source offsets (source_start/source_end)
    are adjusted proportionally so that block.text[source_start:source_end]
    still equals chunk.text[text_start:text_end] in each part.
    """
    first: list[dict] = []
    second: list[dict] = []
    for frag in fragments:
        ts = frag["text_start"]
        te = frag["text_end"]
        ss = frag.get("source_start", 0)
        se = frag.get("source_end", te - ts)
        page_no = frag.get("page_no", 0)
        kind = frag.get("kind", "source")
        block_id = frag["block_id"]

        if ts < split_pos:
            cut = min(te, split_pos)
            # Source offset for the cut point
            src_cut = ss + (cut - ts)
            first.append(_make_fragment(
                block_id, page_no, ss, src_cut, ts, cut, kind,
            ))
        if te > split_pos:
            cut = max(ts, split_pos)
            # Source offset for the cut point
            src_cut = ss + (cut - ts)
            second.append(_make_fragment(
                block_id, page_no, src_cut, se, max(0, ts - split_pos), te - split_pos, kind,
            ))
    return first, second


def validate_chunk_provenance(chunks: list[dict], block_index: dict[str, DocumentBlock]) -> list[str]:
    """Return character-level provenance errors for a set of produced chunks.

    This intentionally validates the production fragment representation rather
    than a parallel test-only model.  It is useful in tests and debug tooling.
    """
    errors: list[str] = []
    for chunk in chunks:
        for fragment in chunk.get("source_fragments_json", []):
            block = block_index.get(fragment["block_id"])
            if block is None:
                errors.append(f"unknown block {fragment['block_id']}")
                continue
            source = block.text[fragment["source_start"]:fragment["source_end"]]
            rendered = chunk["text"][fragment["text_start"]:fragment["text_end"]]
            if source != rendered:
                errors.append(f"chunk {chunk['chunk_index']} fragment {fragment['block_id']} does not map exactly")
    return errors


def _replace_chunk(chunk: dict, text: str, fragments: list[dict]) -> None:
    """Replace a chunk with fragments already aligned to *text* exactly."""
    chunk["text"] = text
    chunk["source_fragments_json"] = fragments
    chunk["source_block_ids"] = list(dict.fromkeys(fragment["block_id"] for fragment in fragments))


def _take_suffix(chunk: dict, count: int) -> tuple[str, list[dict]]:
    split_at = len(chunk["text"]) - count
    retained, moved = _split_fragments(chunk.get("source_fragments_json", []), split_at)
    suffix = chunk["text"][split_at:]
    _replace_chunk(chunk, chunk["text"][:split_at], retained)
    return suffix, moved


def _take_prefix(chunk: dict, count: int) -> tuple[str, list[dict]]:
    moved, retained = _split_fragments(chunk.get("source_fragments_json", []), count)
    prefix = chunk["text"][:count]
    _replace_chunk(chunk, chunk["text"][count:], retained)
    return prefix, moved


def _append(chunk: dict, text: str, fragments: list[dict]) -> None:
    offset = len(chunk["text"])
    shifted = [_make_fragment(
        fragment["block_id"], fragment["page_no"], fragment["source_start"], fragment["source_end"],
        fragment["text_start"] + offset, fragment["text_end"] + offset, fragment.get("kind", "source"),
    ) for fragment in fragments]
    _replace_chunk(chunk, chunk["text"] + text, [*chunk.get("source_fragments_json", []), *shifted])


def _prepend(chunk: dict, text: str, fragments: list[dict]) -> None:
    offset = len(text)
    shifted = [_make_fragment(
        fragment["block_id"], fragment["page_no"], fragment["source_start"], fragment["source_end"],
        fragment["text_start"] + offset, fragment["text_end"] + offset, fragment.get("kind", "source"),
    ) for fragment in chunk.get("source_fragments_json", [])]
    _replace_chunk(chunk, text + chunk["text"], [*fragments, *shifted])


def _adjust_protected_split(chunks: list[dict], idx: int, max_length: int) -> None:
    """Move the boundary between *chunks[idx]* and *chunks[idx+1]* so a
    protected term is no longer split, **without** merging the two chunks
    (merging would exceed *max_length*).

    The partial term is moved to whichever side keeps both resulting
    chunks within *max_length* when possible; otherwise the side that
    yields the smaller maximum length is chosen.
    """
    end_text = chunks[idx]["text"]
    start_text = chunks[idx + 1]["text"]
    for term in _PROTECTED_TERMS:
        for sp in range(1, len(term)):
            suffix = term[-sp:]
            prefix = term[:-sp]
            if not (end_text.endswith(suffix) and start_text.startswith(prefix)):
                continue
            # Option A — move suffix to the start of the next chunk so
            # the whole term lives in chunks[idx + 1].
            new_end_a = end_text[:len(end_text) - len(suffix)] if suffix else end_text
            new_start_a = suffix + start_text
            # Option B — move prefix to the end of the previous chunk so
            # the whole term lives in chunks[idx].
            new_end_b = end_text + prefix
            new_start_b = start_text[len(prefix):] if prefix else start_text

            a_ok = len(new_end_a) <= max_length and len(new_start_a) <= max_length
            b_ok = len(new_end_b) <= max_length and len(new_start_b) <= max_length
            if a_ok:
                moved_text, moved_fragments = _take_suffix(chunks[idx], len(suffix))
                _prepend(chunks[idx + 1], moved_text, moved_fragments)
            elif b_ok:
                moved_text, moved_fragments = _take_prefix(chunks[idx + 1], len(prefix))
                _append(chunks[idx], moved_text, moved_fragments)
            return


def _build_line_source_map(
    table_text: str,
    table_block_info: list[tuple[str, int, str, str]],
) -> list[tuple[str, int, int, int]]:
    """Map each line in table_text to (block_id, page_no, source_start, source_end).

    source_start/source_end are offsets within the block's text (without trailing "\n").
    """
    lines = table_text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    # Build block start/end positions in table_text
    block_ranges: list[tuple[int, int, str, int, str]] = []  # (start, end, bid, page, btxt)
    pos = 0
    for bid, bpage, btxt, btext in table_block_info:
        block_ranges.append((pos, pos + len(btxt), bid, bpage, btxt))
        pos += len(btext)

    line_sources: list[tuple[str, int, int, int]] = []
    line_start = 0  # Position of line start in table_text

    for line in lines:
        line_len = len(line)
        # Find which block this line starts in
        found = False
        for bs, be, bid, bpage, btxt in block_ranges:
            if line_start < be:
                src_start = line_start - bs
                src_start = max(0, min(src_start, len(btxt)))
                src_end = min(src_start + line_len, len(btxt))
                line_sources.append((bid, bpage, src_start, src_end))
                found = True
                break
        if not found and block_ranges:
            bs, be, bid, bpage, btxt = block_ranges[0]
            line_sources.append((bid, bpage, 0, 0))

        line_start += line_len + 1  # +1 for "\n"

    return line_sources


def _split_table_with_fragments(
    table_text: str,
    table_block_info: list[tuple[str, int, str, str]],
    max_length: int,
) -> list[tuple[str, list[dict]]]:
    """Split table text into pieces, returning (piece_text, fragments) for each.

    V7.4.2-01: Each fragment has all 7 required fields.
    Repeated headers are marked with kind="repeated_header".
    """
    lines = table_text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []

    header = lines[0]
    header_len = len(header)

    # Build line-to-source mapping
    line_sources = _build_line_source_map(table_text, table_block_info)
    if not line_sources:
        return []

    header_src = line_sources[0]  # (block_id, page_no, source_start, source_end)

    # Header row alone exceeds the limit — treat as single long line
    if len(header) > max_length:
        full_text = table_text.strip()
        pieces = _split_long_line(full_text, max_length)
        result = []
        text_offset = 0
        for piece in pieces:
            # Find source for this piece by matching text
            frags = []
            piece_start = 0
            for src_bid, src_page, src_ss, src_se in line_sources:
                src_text = None
                for bid, bpage, btxt, btext in table_block_info:
                    if bid == src_bid:
                        src_text = btxt[src_ss:src_se]
                        break
                if src_text and src_text in piece:
                    frag_ts = piece.index(src_text)
                    frag_te = frag_ts + len(src_text)
                    frags.append(_make_fragment(
                        src_bid, src_page, src_ss, src_se,
                        frag_ts, frag_te, "source",
                    ))
            if not frags:
                frags.append(_make_fragment(
                    header_src[0], header_src[1],
                    header_src[2], min(header_src[3], len(piece)),
                    0, len(piece), "source",
                ))
            result.append((piece, frags))
        return result

    header_prefix = header + "\n"
    data_line_sources = line_sources[1:]  # Skip header
    data_lines = lines[1:]

    result: list[tuple[str, list[dict]]] = []
    current_text = header_prefix
    current_frags: list[dict] = []

    # First piece: header is source
    current_frags.append(_make_fragment(
        header_src[0], header_src[1],
        header_src[2], header_src[3],
        0, header_len, "source",
    ))

    def _make_header_frag(kind: str) -> dict:
        """Create a fragment for the (possibly repeated) header."""
        return _make_fragment(
            header_src[0], header_src[1],
            header_src[2], header_src[3],
            0, header_len, kind,
        )

    data_idx = 0
    for line in data_lines:
        if not line.strip():
            data_idx += 1
            continue

        src = data_line_sources[data_idx] if data_idx < len(data_line_sources) else header_src

        if len(line) > max_length:
            # Sub-split a long row
            if current_text.strip():
                result.append((current_text.rstrip("\n"), current_frags))
                current_text = header_prefix
                current_frags = [_make_header_frag("repeated_header")]

            sub_lines = _split_long_line(line, max_length)
            sub_offset = 0  # Offset within the line's source
            for sub in sub_lines:
                if not current_text:
                    current_text = header_prefix
                    current_frags = [_make_header_frag("repeated_header")]
                if len(current_text) + len(sub) + 1 > max_length and current_text.strip():
                    result.append((current_text.rstrip("\n"), current_frags))
                    current_text = header_prefix
                    current_frags = [_make_header_frag("repeated_header")]
                sub_start = len(current_text)
                current_text += sub + "\n"
                current_frags.append(_make_fragment(
                    src[0], src[1],
                    src[2] + sub_offset, src[2] + sub_offset + len(sub),
                    sub_start, sub_start + len(sub), "source",
                ))
                sub_offset += len(sub)
        else:
            if not current_text:
                current_text = header_prefix
                current_frags = [_make_header_frag("repeated_header")]
            if len(current_text) + len(line) + 1 > max_length and current_text.strip():
                result.append((current_text.rstrip("\n"), current_frags))
                current_text = header_prefix
                current_frags = [_make_header_frag("repeated_header")]
            line_start = len(current_text)
            current_text += line + "\n"
            current_frags.append(_make_fragment(
                src[0], src[1],
                src[2], src[3],
                line_start, line_start + len(line), "source",
            ))

        data_idx += 1

    if current_text.strip():
        result.append((current_text.rstrip("\n"), current_frags))

    return result


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
                current_fragments = [_make_fragment(block.block_id, page_no, 0, len(block.text), 0, len(block.text))]
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
                    # split it at newline boundaries (and sub-split any
                    # individual line that still exceeds max_length).
                    if len(item_text) > max_length:
                        # Flush current content first
                        if current_text.strip():
                            _flush("list")
                        # Split the list block text at newline boundaries
                        lines = b.text.split("\n")
                        src_offset = 0  # Offset within b.text
                        for line in lines:
                            if not line.strip():
                                src_offset += len(line) + 1  # +1 for "\n"
                                continue
                            # A single list line may itself exceed
                            # max_length — sub-split it at sentence /
                            # space / hard-limit boundaries.
                            if len(line) > max_length:
                                sub_lines = _split_long_line(line, max_length)
                                sub_offset = 0  # Offset within line
                                for sub in sub_lines:
                                    if len(current_text) + len(sub) + 1 > max_length and current_text.strip():
                                        _flush("list")
                                    block_start = len(current_text)
                                    current_text += sub + "\n"
                                    current_block_ids.append(b.block_id)
                                    current_page_nos.add(page_no)
                                    current_fragments.append(_make_fragment(
                                        b.block_id, page_no,
                                        src_offset + sub_offset,
                                        src_offset + sub_offset + len(sub),
                                        block_start, block_start + len(sub),
                                    ))
                                    sub_offset += len(sub)
                            else:
                                if len(current_text) + len(line) + 1 > max_length and current_text.strip():
                                    _flush("list")
                                block_start = len(current_text)
                                current_text += line + "\n"
                                current_block_ids.append(b.block_id)
                                current_page_nos.add(page_no)
                                current_fragments.append(_make_fragment(
                                    b.block_id, page_no,
                                    src_offset, src_offset + len(line),
                                    block_start, block_start + len(line),
                                ))
                            src_offset += len(line) + 1  # +1 for "\n"
                        i += 1
                        continue
                    # If adding this item exceeds max_length, flush and start new
                    if len(current_text) + len(item_text) > max_length and current_text.strip():
                        _flush("list")
                    block_start = len(current_text)
                    current_text += item_text
                    current_block_ids.append(b.block_id)
                    current_page_nos.add(page_no)
                    current_fragments.append(_make_fragment(
                        b.block_id, page_no, 0, len(b.text),
                        block_start, block_start + len(b.text),
                    ))
                    i += 1
                continue

            # Table → collect all consecutive table blocks, keep together
            if _is_table(block):
                table_text = ""
                table_ids: list[str] = []
                # V7.4.2-01: Track (block_id, page_no, block_text, btext) for provenance
                table_block_info: list[tuple[str, int, str, str]] = []
                while i < len(blocks) and _is_table(blocks[i]):
                    b = blocks[i]
                    btext = b.text + "\n"
                    table_text += btext
                    table_ids.append(b.block_id)
                    table_block_info.append((b.block_id, page_no, b.text, btext))
                    i += 1

                if len(current_text) + len(table_text) > max_length:
                    # The table (possibly with current text) is too long —
                    # flush current content, then split the table text at
                    # row boundaries (with header repetition).
                    if current_text.strip():
                        _flush("table")
                    # V7.4.2-01: Split with proper provenance tracking
                    pieces_with_frags = _split_table_with_fragments(
                        table_text, table_block_info, max_length,
                    )
                    for piece_text, piece_frags in pieces_with_frags:
                        if len(current_text) + len(piece_text) + 1 > max_length and current_text.strip():
                            _flush("table")
                        piece_start = len(current_text)
                        current_text += piece_text + "\n"
                        # Adjust fragment text offsets to be relative to current_text
                        for frag in piece_frags:
                            current_fragments.append(_make_fragment(
                                frag["block_id"], frag["page_no"],
                                frag["source_start"], frag["source_end"],
                                piece_start + frag["text_start"],
                                piece_start + frag["text_end"],
                                frag["kind"],
                            ))
                        current_block_ids.extend(table_ids)
                        current_page_nos.add(page_no)
                else:
                    table_start = len(current_text)
                    offset = 0
                    for bid, bpage, btxt, btext in table_block_info:
                        # V7.4.2-01: Include all 7 fields, exclude trailing "\n" from text_end
                        current_fragments.append(_make_fragment(
                            bid, bpage, 0, len(btxt),
                            table_start + offset, table_start + offset + len(btxt),
                        ))
                        offset += len(btext)
                    current_text += table_text
                    current_block_ids.extend(table_ids)
                    current_page_nos.add(page_no)
                continue

            # Body block
            block_text = block.text

            # A single body block may be longer than max_length.  Split its
            # original text first so every resulting fragment remains a direct
            # character slice of the originating block.
            if len(block_text) > max_length:
                if current_text.strip():
                    _flush("paragraph")
                source_offset = 0
                for piece in _split_long_line(block_text, max_length):
                    current_text = piece + "\n"
                    current_block_ids = [block.block_id]
                    current_page_nos = {page_no}
                    current_fragments = [_make_fragment(
                        block.block_id, page_no, source_offset, source_offset + len(piece), 0, len(piece),
                    )]
                    source_offset += len(piece)
                    _flush("hard_limit_fallback")
                i += 1
                continue

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
                    current_fragments = [_make_fragment(block.block_id, page_no, 0, len(block_text), 0, len(block_text))]
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
                    block_text_end = new_block_start + len(block_text)  # Exclude "\n"
                    if new_block_start < split_pos:
                        frag_te = min(block_text_end, split_pos)
                        if new_block_start < frag_te:
                            first_frags.append(_make_fragment(
                                block.block_id, page_no, 0, frag_te - new_block_start,
                                new_block_start, frag_te,
                            ))
                    if block_text_end > split_pos:
                        frag_ts = max(0, new_block_start - split_pos)
                        frag_te = block_text_end - split_pos
                        if frag_ts < frag_te:
                            second_frags.append(_make_fragment(
                                block.block_id, page_no,
                                max(0, split_pos - new_block_start), len(block_text),
                                frag_ts, frag_te,
                            ))

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
                current_fragments = [_make_fragment(block.block_id, page_no, 0, len(block_text), 0, len(block_text))]
            else:
                # Add block to current chunk
                block_start = len(current_text)
                current_text += block_text + "\n"
                current_block_ids.append(block.block_id)
                current_page_nos.add(page_no)
                current_fragments.append(_make_fragment(
                    block.block_id, page_no, 0, len(block_text),
                    block_start, block_start + len(block_text),
                ))

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
            # max_length is a hard production contract: never merge a
            # protected term when that would overflow it.
            if len(merged_text) > max_length:
                _adjust_protected_split(chunks, idx, max_length)
                continue
            merged_ids = list(chunks[idx]["source_block_ids"]) + list(chunks[idx + 1]["source_block_ids"])
            merged_frags = list(chunks[idx].get("source_fragments_json", []))
            # Adjust second chunk's fragments to be relative to the merged text
            offset = len(end_text) + 1  # +1 for the newline
            for frag in chunks[idx + 1].get("source_fragments_json", []):
                merged_frags.append(_make_fragment(
                    frag["block_id"],
                    frag.get("page_no", 0),
                    frag.get("source_start", 0),
                    frag.get("source_end", frag["text_end"] - frag["text_start"]),
                    frag["text_start"] + offset,
                    frag["text_end"] + offset,
                    frag.get("kind", "source"),
                ))
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
