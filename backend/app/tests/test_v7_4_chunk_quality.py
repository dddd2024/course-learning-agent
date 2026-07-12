"""V7.4-02: Cleaning and chunk quality tests.

Tests that:
- clean_pages() is called exactly once per page (no double cleaning)
- Line-level noise within a block is removed (not just whole-block removal)
- Fragment offsets are consistent with the stripped chunk.text
- Block IDs preserve insertion order (not set-shuffled)
- Large list blocks (>1000 chars) are properly split
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk
from app.services.document_cleaning_pipeline import clean_document_pages


def _make_page(page_no, blocks_data):
    """Build a DocumentPage from (block_type, text) tuples."""
    blocks = []
    for i, (bt, text) in enumerate(blocks_data):
        blocks.append(DocumentBlock(
            block_id=f"p{page_no}b{i}",
            page_no=page_no,
            block_type=bt,
            reading_order=i,
            text=text,
            source_kind="txt",
        ))
    return DocumentPage(page_no=page_no, blocks=blocks)


def test_clean_pages_called_once_per_page():
    """clean_document_pages must not call clean_pages twice (P1-02)."""
    pages = [_make_page(1, [("body", "操作系统概述\n第1页"), ("body", "进程管理")])]

    with patch(
        "app.services.document_cleaning_pipeline.clean_pages"
    ) as mock_clean:
        mock_clean.return_value = [MagicMock(decisions=[])]
        clean_document_pages(pages)
        assert mock_clean.call_count == 1, (
            f"clean_pages should be called once, got {mock_clean.call_count}"
        )


def test_line_level_noise_removed_within_block():
    """Noise lines within a multi-line block must be removed (P1-01)."""
    # A block with 3 lines, one of which is a page number
    pages = [_make_page(1, [(
        "body",
        "操作系统概述\n第1页\n进程管理是操作系统的核心功能"
    )])]

    cleaned = clean_document_pages(pages)
    assert len(cleaned) == 1
    page = cleaned[0]
    # The page number line should be removed from the block text
    all_text = page.text
    assert "第1页" not in all_text
    assert "操作系统概述" in all_text
    assert "进程管理" in all_text


def test_fragment_offsets_consistent_with_stripped_text():
    """Fragment offsets must be valid indices into the stripped chunk.text (P1-03)."""
    # Create enough text to produce at least 2 chunks
    long_text = (
        "操作系统是管理计算机硬件和软件资源的程序。\n"
        "它为应用程序提供接口，并为用户提供服务。\n"
        "进程管理是操作系统的核心功能之一，负责进程的创建、调度和销毁。\n"
        "内存管理负责分配和回收内存资源，虚拟内存将物理内存扩展到磁盘。\n"
        "文件系统管理持久化存储的数据，提供文件的创建、删除、读写接口。\n"
        "设备驱动程序管理各种输入输出设备，包括键盘、鼠标、显示器等。\n"
        "网络协议栈实现网络通信功能，TCP/IP协议栈分为四层。\n"
        "安全机制保护系统免受恶意攻击，包括访问控制和加密技术。\n"
        "操作系统是管理计算机硬件和软件资源的程序。\n"
        "它为应用程序提供接口，并为用户提供服务。\n"
        "进程管理是操作系统的核心功能之一，负责进程的创建、调度和销毁。\n"
        "内存管理负责分配和回收内存资源，虚拟内存将物理内存扩展到磁盘。\n"
        "文件系统管理持久化存储的数据，提供文件的创建、删除、读写接口。\n"
        "设备驱动程序管理各种输入输出设备，包括键盘、鼠标、显示器等。\n"
        "网络协议栈实现网络通信功能，TCP/IP协议栈分为四层。\n"
        "安全机制保护系统免受恶意攻击，包括访问控制和加密技术。\n"
    )
    pages = [_make_page(1, [("heading", "# 操作系统"), ("body", long_text)])]
    chunks = semantic_chunk(pages, target_length=400, max_length=600)

    assert len(chunks) >= 2

    for chunk in chunks:
        text = chunk["text"]
        fragments = chunk.get("source_fragments_json", [])
        for frag in fragments:
            start = frag["text_start"]
            end = frag["text_end"]
            # Offsets must be within bounds of the stripped text
            assert 0 <= start <= end <= len(text), (
                f"Fragment offset out of bounds: [{start}, {end}) "
                f"for text of length {len(text)}"
            )


def test_block_ids_preserve_insertion_order():
    """Block IDs in source_block_ids must preserve insertion order (P1-04)."""
    pages = [_make_page(1, [
        ("heading", "# Chapter 1"),
        ("body", "Block A content that is long enough to be meaningful. " * 10),
        ("body", "Block B content that is long enough to be meaningful. " * 10),
        ("body", "Block C content that is long enough to be meaningful. " * 10),
    ])]
    chunks = semantic_chunk(pages, target_length=200, max_length=400)

    for chunk in chunks:
        ids = chunk["source_block_ids"]
        # Verify no duplicates
        assert len(ids) == len(set(ids)), f"Duplicate block IDs: {ids}"
        # Verify order is preserved (not set-shuffled)
        # The IDs should appear in the order blocks were encountered
        # We check that the IDs are monotonically ordered by their index
        indices = [int(bid.split("b")[1]) for bid in ids]
        assert indices == sorted(indices), (
            f"Block IDs not in insertion order: {ids} (indices: {indices})"
        )


def test_large_list_block_split():
    """A single list block exceeding max_length must be split (P1-04)."""
    # Create a list block with many items
    items = [f"- 列表项 {i}: 这是一个足够长的列表项内容用于测试。" for i in range(30)]
    list_text = "\n".join(items)
    pages = [_make_page(1, [("list", list_text)])]
    chunks = semantic_chunk(pages, target_length=300, max_length=500)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk["text"]) <= 600  # Allow some slack for newlines
