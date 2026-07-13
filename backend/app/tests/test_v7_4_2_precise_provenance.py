"""V7.4.2-01: Precise chunk provenance and strict length tests.

验证：
1. 每个 fragment 包含 7 个必填字段：block_id, page_no, source_start, source_end, text_start, text_end, kind
2. block.text[source_start:source_end] == chunk.text[text_start:text_end] （逐字符验证）
3. kind 只能是 "source" 或 "repeated_header"
4. 不存在指向首 block 的 fallback
5. len(chunk.text) <= max_length 为硬约束
6. 长单行列表、50行列表、20行表格、长单行表格、跨页、受保护术语、20次确定性
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk

REQUIRED_FRAGMENT_FIELDS = {
    "block_id", "page_no", "source_start", "source_end",
    "text_start", "text_end", "kind",
}
VALID_KINDS = {"source", "repeated_header"}


def _make_page(page_no: int, blocks: list[DocumentBlock]) -> DocumentPage:
    return DocumentPage(page_no=page_no, blocks=blocks)


def _make_block(block_id: str, page_no: int, block_type: str, text: str) -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id, page_no=page_no, block_type=block_type,
        reading_order=0, text=text,
    )


def _build_block_index(pages: list[DocumentPage]) -> dict[str, DocumentBlock]:
    """Build block_id -> DocumentBlock lookup."""
    idx = {}
    for page in pages:
        for block in page.blocks:
            idx[block.block_id] = block
    return idx


def _verify_fragments(chunk: dict, block_index: dict[str, DocumentBlock]) -> list[str]:
    """Verify all fragment constraints. Returns list of error messages (empty = pass)."""
    errors = []
    fragments = chunk.get("source_fragments_json", [])
    if not fragments:
        errors.append(f"Chunk {chunk.get('chunk_index')}: no fragments")
        return errors

    for i, frag in enumerate(fragments):
        # Check required fields
        missing = REQUIRED_FRAGMENT_FIELDS - set(frag.keys())
        if missing:
            errors.append(f"Chunk {chunk['chunk_index']} frag[{i}]: missing fields {missing}")
            continue

        # Check kind
        if frag["kind"] not in VALID_KINDS:
            errors.append(f"Chunk {chunk['chunk_index']} frag[{i}]: invalid kind '{frag['kind']}'")

        # Check block exists
        block = block_index.get(frag["block_id"])
        if block is None:
            errors.append(f"Chunk {chunk['chunk_index']} frag[{i}]: block_id '{frag['block_id']}' not found")
            continue

        # Check page_no matches block
        if frag["page_no"] != block.page_no:
            errors.append(
                f"Chunk {chunk['chunk_index']} frag[{i}]: page_no mismatch "
                f"frag={frag['page_no']} block={block.page_no}"
            )

        # Core verification: block.text[source_start:source_end] == chunk.text[text_start:text_end]
        source_slice = block.text[frag["source_start"]:frag["source_end"]]
        text_slice = chunk["text"][frag["text_start"]:frag["text_end"]]
        if source_slice != text_slice:
            errors.append(
                f"Chunk {chunk['chunk_index']} frag[{i}]: content mismatch "
                f"block.text[{frag['source_start']}:{frag['source_end']}] != "
                f"chunk.text[{frag['text_start']}:{frag['text_end']}]\n"
                f"  source: {source_slice[:50]!r}\n"
                f"  chunk:  {text_slice[:50]!r}"
            )

    return errors


class TestFragmentContract:
    """V7.4.2-01: Fragment 合同验证。"""

    def test_fragments_have_all_required_fields(self):
        """每个 fragment 必须包含 7 个必填字段。"""
        page = _make_page(1, [_make_block("p1b1", 1, "body", "这是一个测试内容。")])
        chunks = semantic_chunk([page], target_length=1000, max_length=2000)
        assert len(chunks) >= 1
        for chunk in chunks:
            for frag in chunk["source_fragments_json"]:
                missing = REQUIRED_FRAGMENT_FIELDS - set(frag.keys())
                assert not missing, f"Fragment missing fields: {missing}"

    def test_kind_is_source_or_repeated_header(self):
        """kind 只能是 source 或 repeated_header。"""
        page = _make_page(1, [_make_block("p1b1", 1, "body", "测试内容。")])
        chunks = semantic_chunk([page], target_length=1000, max_length=2000)
        for chunk in chunks:
            for frag in chunk["source_fragments_json"]:
                assert frag["kind"] in VALID_KINDS, f"Invalid kind: {frag['kind']}"


class TestCharacterLevelVerification:
    """V7.4.2-01: 逐字符验证 block.text[source_start:source_end] == chunk.text[text_start:text_end]。"""

    def test_simple_body_block_provenance(self):
        """单个 body block 的 fragment 必须精确映射。"""
        text = "操作系统是管理计算机硬件与软件资源的程序。"
        page = _make_page(1, [_make_block("p1b1", 1, "body", text)])
        chunks = semantic_chunk([page], target_length=1000, max_length=2000)
        block_index = _build_block_index([page])
        for chunk in chunks:
            errors = _verify_fragments(chunk, block_index)
            assert not errors, "\n".join(errors)

    def test_multiple_blocks_provenance(self):
        """多个 block 的 fragment 必须各自精确映射。"""
        pages = [_make_page(1, [
            _make_block("p1b1", 1, "body", "第一段内容。"),
            _make_block("p1b2", 1, "body", "第二段内容。"),
            _make_block("p1b3", 1, "body", "第三段内容。"),
        ])]
        chunks = semantic_chunk(pages, target_length=1000, max_length=2000)
        block_index = _build_block_index(pages)
        for chunk in chunks:
            errors = _verify_fragments(chunk, block_index)
            assert not errors, "\n".join(errors)

    def test_cross_page_provenance(self):
        """跨页 chunk 的 fragment 必须精确映射到各自页面的 block。"""
        pages = [
            _make_page(1, [_make_block("p1b1", 1, "body", "第一页内容。")]),
            _make_page(2, [_make_block("p2b1", 2, "body", "第二页内容。")]),
        ]
        chunks = semantic_chunk(pages, target_length=1000, max_length=2000)
        block_index = _build_block_index(pages)
        for chunk in chunks:
            errors = _verify_fragments(chunk, block_index)
            assert not errors, "\n".join(errors)


class TestNoFirstBlockFallback:
    """V7.4.2-01: 不存在指向首 block 的 fallback。"""

    def test_split_table_no_first_block_fallback(self):
        """分割表格时，每个 piece 的 fragment 不应全部指向首 table block。"""
        header = "列A\t列B\t列C"
        rows = [f"数据{i}A\t数据{i}B\t数据{i}C" for i in range(1, 21)]
        text = header + "\n" + "\n".join(rows)
        page = _make_page(1, [_make_block("p1b1", 1, "table", text)])
        chunks = semantic_chunk([page], target_length=50, max_length=80)

        # When table is split, fragments should not all point to same block_id
        # with full text range — they should have precise source_start/source_end
        block_index = _build_block_index([page])
        for chunk in chunks:
            errors = _verify_fragments(chunk, block_index)
            assert not errors, "\n".join(errors)

    def test_repeated_header_has_correct_kind(self):
        """表格分割时重复的表头 fragment 必须有 kind=repeated_header。"""
        header = "列A\t列B"
        rows = [f"行{i}A\t行{i}B" for i in range(1, 31)]
        text = header + "\n" + "\n".join(rows)
        page = _make_page(1, [_make_block("p1b1", 1, "table", text)])
        chunks = semantic_chunk([page], target_length=50, max_length=80)

        # At least one fragment should be repeated_header if table is split
        all_kinds = []
        for chunk in chunks:
            for frag in chunk["source_fragments_json"]:
                all_kinds.append(frag["kind"])
        # If there are multiple chunks, we expect repeated_header
        if len(chunks) > 1:
            assert "repeated_header" in all_kinds, \
                "Expected repeated_header kind when table is split"


class TestHardMaxLength:
    """V7.4.2-01: max_length 为硬约束。"""

    def test_long_single_line_list(self):
        """3000 字符单行列表必须被分割，每个 chunk <= max_length。"""
        long_line = "操作系统是管理计算机硬件与软件资源的程序。" * 100
        page = _make_page(1, [_make_block("p1b1", 1, "list", long_line)])
        chunks = semantic_chunk([page], target_length=400, max_length=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 500, \
                f"Chunk {chunk['chunk_index']}: {len(chunk['text'])} > 500"

    def test_50_line_list(self):
        """50 行列表必须被分割，每个 chunk <= max_length。"""
        lines = [f"列表项第{i}行：这是第{i}个条目的内容描述。" for i in range(1, 51)]
        text = "\n".join(lines)
        page = _make_page(1, [_make_block("p1b1", 1, "list", text)])
        chunks = semantic_chunk([page], target_length=200, max_length=300)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 300

    def test_20_row_table(self):
        """20 行表格必须被分割，每个 chunk <= max_length。"""
        header = "列A\t列B\t列C"
        rows = [f"数据{i}A\t数据{i}B\t数据{i}C" for i in range(1, 21)]
        text = header + "\n" + "\n".join(rows)
        page = _make_page(1, [_make_block("p1b1", 1, "table", text)])
        chunks = semantic_chunk([page], target_length=100, max_length=150)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 150

    def test_long_single_line_table(self):
        """3000 字符单行表格必须被安全分割。"""
        long_line = "列A\t列B\t列C\t" + "数据内容" * 500
        page = _make_page(1, [_make_block("p1b1", 1, "table", long_line)])
        chunks = semantic_chunk([page], target_length=400, max_length=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk["text"]) <= 500

    def test_protected_term_respects_max_length(self):
        """受保护术语合并时必须遵守 max_length。"""
        text1 = "A" * 480 + "TCP/"
        text2 = "/IP" + "B" * 480
        page = _make_page(1, [
            _make_block("p1b1", 1, "body", text1),
            _make_block("p1b2", 1, "body", text2),
        ])
        chunks = semantic_chunk([page], target_length=400, max_length=500)
        for chunk in chunks:
            assert len(chunk["text"]) <= 500


class TestDeterministicOutput:
    """V7.4.2-01: 20 次确定性输出。"""

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


class TestFullProvenanceVerification:
    """V7.4.2-01: 所有场景的完整 provenance 验证。"""

    def test_all_scenarios_verified(self):
        """所有测试场景的 fragment 必须通过逐字符验证。"""
        scenarios = [
            # Simple body
            ([_make_page(1, [_make_block("p1b1", 1, "body", "简单内容。")])], 1000, 2000),
            # Long single-line list
            ([_make_page(1, [_make_block("p1b1", 1, "list", "项目" * 500)])], 400, 500),
            # 50-line list
            ([_make_page(1, [_make_block("p1b1", 1, "list", "\n".join(f"行{i}" for i in range(50)))])], 200, 300),
            # 20-row table
            ([_make_page(1, [_make_block("p1b1", 1, "table", "H1\tH2\n" + "\n".join(f"R{i}A\tR{i}B" for i in range(20)))])], 100, 150),
            # Cross-page
            ([_make_page(1, [_make_block("p1b1", 1, "body", "第一页。")]),
              _make_page(2, [_make_block("p2b1", 2, "body", "第二页。")])], 1000, 2000),
        ]

        for pages, target, max_len in scenarios:
            chunks = semantic_chunk(pages, target_length=target, max_length=max_len)
            block_index = _build_block_index(pages)
            for chunk in chunks:
                errors = _verify_fragments(chunk, block_index)
                assert not errors, f"Scenario failed:\n{chr(10).join(errors)}"
