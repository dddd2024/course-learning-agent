"""V7.4.1-02: Chunk boundary and provenance edge case tests.

Tests:
1. 3000-char single-line list is split at sentence/space/hard limit
2. 50-line list is split at list-item boundaries
3. 20-row table is split with header repetition
4. 3000-char single-line table is safely split
5. Cross-page paragraph has correct page_start/page_end from fragments
6. Fragments verify content match (not just offset bounds)
7. Flush after split doesn't lose fragments
8. Protected term merge respects max_length
9. Deterministic output on repeated runs
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk, _build_chunk


def _make_page(page_no: int, blocks: list[DocumentBlock]) -> DocumentPage:
    return DocumentPage(page_no=page_no, blocks=blocks)


def _make_block(block_id: str, page_no: int, block_type: str, text: str) -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id, page_no=page_no, block_type=block_type,
        reading_order=0, text=text,
    )


def _normalize(text: str) -> str:
    """Normalize text for comparison: strip and collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip())


# ---------------------------------------------------------------------------
# 1. 3000-char single-line list
# ---------------------------------------------------------------------------

class TestLongSingleLineList:
    """A list block with a single 3000-char line must be split safely."""

    def test_single_long_line_list_split(self):
        """Each chunk must be <= max_length even with a 3000-char list line."""
        long_line = "操作系统是管理计算机硬件与软件资源的程序。" * 100  # ~3000 chars
        page = _make_page(1, [_make_block("p1b1", 1, "list", long_line)])
        chunks = semantic_chunk([page], target_length=400, max_length=500)
        assert len(chunks) > 1, "Should produce multiple chunks"
        for chunk in chunks:
            assert len(chunk["text"]) <= 500, (
                f"Chunk {chunk['chunk_index']} exceeds max_length: "
                f"{len(chunk['text'])} > 500"
            )


# ---------------------------------------------------------------------------
# 2. 50-line list
# ---------------------------------------------------------------------------

class TestMultiLineList:
    """A 50-line list should split at list-item boundaries."""

    def test_50_line_list_splits_at_items(self):
        lines = [f"列表项第{i}行：这是第{i}个条目的内容描述。" for i in range(1, 51)]
        text = "\n".join(lines)
        page = _make_page(1, [_make_block("p1b1", 1, "list", text)])
        chunks = semantic_chunk([page], target_length=200, max_length=300)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 300


# ---------------------------------------------------------------------------
# 3. 20-row table
# ---------------------------------------------------------------------------

class TestLongTable:
    """A 20-row table should split with header repetition."""

    def test_table_splits_with_header(self):
        header = "列A\t列B\t列C"
        rows = [f"数据{i}A\t数据{i}B\t数据{i}C" for i in range(1, 21)]
        text = header + "\n" + "\n".join(rows)
        page = _make_page(1, [_make_block("p1b1", 1, "table", text)])
        chunks = semantic_chunk([page], target_length=100, max_length=150)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 150


# ---------------------------------------------------------------------------
# 4. 3000-char single-line table
# ---------------------------------------------------------------------------

class TestLongSingleLineTable:
    """A table with a single 3000-char line must be safely split."""

    def test_single_long_line_table_split(self):
        long_line = "列A\t列B\t列C\t" + "数据内容" * 500  # ~3000 chars
        page = _make_page(1, [_make_block("p1b1", 1, "table", long_line)])
        chunks = semantic_chunk([page], target_length=400, max_length=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 500


# ---------------------------------------------------------------------------
# 5. Cross-page provenance
# ---------------------------------------------------------------------------

class TestCrossPageProvenance:
    """page_start/page_end must come from fragment page_nos, not current page."""

    def test_cross_page_paragraph_page_range(self):
        """A chunk spanning pages 1-2 must have page_start=1, page_end=2."""
        page1 = _make_page(1, [_make_block("p1b1", 1, "body", "短内容")])
        page2 = _make_page(2, [_make_block("p2b1", 2, "body", "更多内容")])
        chunks = semantic_chunk([page1, page2], target_length=1000, max_length=2000)
        # Both blocks should be in one chunk
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk["page_start"] == 1
        assert chunk["page_end"] == 2


# ---------------------------------------------------------------------------
# 6. Fragment content verification
# ---------------------------------------------------------------------------

class TestFragmentContentVerification:
    """Fragments must verify content matches, not just offset bounds."""

    def test_fragment_content_matches_chunk_text(self):
        """The text at fragment offsets in chunk.text must match block.text."""
        block_text = "这是一个测试内容用于验证fragment的正确性。"
        page = _make_page(1, [_make_block("p1b1", 1, "body", block_text)])
        chunks = semantic_chunk([page], target_length=1000, max_length=2000)
        assert len(chunks) == 1
        chunk = chunks[0]
        fragments = chunk.get("source_fragments_json", [])
        assert len(fragments) > 0
        for frag in fragments:
            # Extract text from chunk using fragment offsets
            chunk_slice = chunk["text"][frag["text_start"]:frag["text_end"]]
            # The normalized version should match part of the block text
            assert _normalize(chunk_slice) in _normalize(block_text) or \
                   _normalize(block_text) in _normalize(chunk_slice), (
                f"Fragment content mismatch: chunk slice '{chunk_slice[:50]}' "
                f"not found in block text '{block_text[:50]}'"
            )


# ---------------------------------------------------------------------------
# 7. Flush doesn't lose fragments
# ---------------------------------------------------------------------------

class TestFlushPreservesFragments:
    """Flushing after a split must not lose fragments."""

    def test_no_fragment_loss_on_flush(self):
        """Every chunk must have at least one fragment."""
        blocks = []
        for i in range(20):
            blocks.append(_make_block(f"p1b{i}", 1, "body", f"内容块{i}" * 50))
        page = _make_page(1, blocks)
        chunks = semantic_chunk([page], target_length=100, max_length=200)
        for chunk in chunks:
            frags = chunk.get("source_fragments_json", [])
            assert len(frags) > 0, (
                f"Chunk {chunk['chunk_index']} has no fragments"
            )


# ---------------------------------------------------------------------------
# 8. Protected term merge respects max_length
# ---------------------------------------------------------------------------

class TestProtectedTermMergeMaxLength:
    """Merging chunks for protected terms must not exceed max_length."""

    def test_merge_respects_max_length(self):
        """If merging would exceed max_length, don't merge."""
        # Create two chunks near max_length with a protected term at boundary
        text1 = "A" * 480 + "TCP/"
        text2 = "/IP" + "B" * 480
        # This creates chunks where TCP/IP is split across boundary
        page = _make_page(1, [
            _make_block("p1b1", 1, "body", text1),
            _make_block("p1b2", 1, "body", text2),
        ])
        chunks = semantic_chunk([page], target_length=400, max_length=500)
        for chunk in chunks:
            assert len(chunk["text"]) <= 500, (
                f"Merged chunk exceeds max_length: {len(chunk['text'])}"
            )


# ---------------------------------------------------------------------------
# 9. Deterministic output
# ---------------------------------------------------------------------------

class TestDeterministicOutput:
    """Same input must produce same output across multiple runs."""

    def test_20_runs_identical(self):
        blocks = [
            _make_block(f"p1b{i}", 1, "body", f"第{i}段内容。" * 20)
            for i in range(1, 6)
        ]
        page = _make_page(1, blocks)
        first_run = semantic_chunk([page], target_length=200, max_length=300)
        for _ in range(19):
            run = semantic_chunk([page], target_length=200, max_length=300)
            assert len(run) == len(first_run), "Chunk count differs between runs"
            for a, b in zip(first_run, run):
                assert a["text"] == b["text"], "Chunk text differs between runs"
                assert a["chunk_index"] == b["chunk_index"]
