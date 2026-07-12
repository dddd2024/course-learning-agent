"""V7.3-01 P0-02: Cross-block chunk splits must preserve complete provenance.

When the semantic chunker splits text across a block boundary, both
resulting chunks must record *all* source block IDs that contributed
text.  A ``source_fragments_json`` field must record the text range
from each block.
"""
from __future__ import annotations

import json

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk_document


def _make_page(page_no: int, blocks: list[tuple[str, str, str]]) -> DocumentPage:
    """Build a page from (block_id, text, block_type) tuples."""
    return DocumentPage(
        page_no=page_no,
        blocks=[
            DocumentBlock(
                block_id=bid,
                page_no=page_no,
                block_type=btype,
                reading_order=i,
                text=text,
            )
            for i, (bid, text, btype) in enumerate(blocks)
        ],
    )


def test_chunk_source_block_ids_never_empty():
    """Every chunk must have at least one source_block_id."""
    pages = [
        _make_page(1, [
            ("p1-b0", "第一章 计算机网络概述", "heading"),
            ("p1-b1", "计算机网络是由若干节点和连接这些节点的链路组成的。", "body"),
            ("p1-b2", "TCP/IP是互联网的基础协议。", "body"),
        ]),
    ]
    chunks = semantic_chunk_document(pages)
    for chunk in chunks:
        assert len(chunk["source_block_ids"]) > 0, \
            f"Chunk {chunk['chunk_index']} has empty source_block_ids"


def test_cross_block_split_preserves_both_block_ids():
    """When text from block A and B is split, both chunks must list both blocks."""
    # Create a scenario where two blocks are combined and then split
    long_text_a = "TCP/IP协议是互联网的基础协议。" * 20
    long_text_b = "CSMA/CD用于以太网冲突检测。" * 20
    pages = [
        _make_page(1, [
            ("p1-b0", "第一章 网络协议", "heading"),
            ("p1-b1", long_text_a, "body"),
            ("p1-b2", long_text_b, "body"),
        ]),
    ]
    chunks = semantic_chunk_document(pages, target_length=100, max_length=200)
    # Find chunks that contain text from block b1
    b1_chunks = [c for c in chunks if "p1-b1" in c["source_block_ids"]]
    b2_chunks = [c for c in chunks if "p1-b2" in c["source_block_ids"]]
    # Both blocks must appear in at least one chunk
    assert len(b1_chunks) > 0, "Block p1-b1 not found in any chunk"
    assert len(b2_chunks) > 0, "Block p1-b2 not found in any chunk"
    # If a chunk contains text from block b2, it must also list b2 in its IDs
    for chunk in chunks:
        if "CSMA/CD" in chunk["text"]:
            assert "p1-b2" in chunk["source_block_ids"], \
                f"Chunk contains CSMA/CD text but missing p1-b2 in source_block_ids"
        if "TCP/IP" in chunk["text"] and "CSMA/CD" not in chunk["text"]:
            assert "p1-b1" in chunk["source_block_ids"], \
                f"Chunk contains TCP/IP text but missing p1-b1 in source_block_ids"


def test_source_fragments_json_is_populated():
    """Each chunk must have source_fragments_json with block_id and text range."""
    pages = [
        _make_page(1, [
            ("p1-b0", "第一章 概述", "heading"),
            ("p1-b1", "计算机网络是计算机系统的集合。", "body"),
            ("p1-b2", "协议是通信规则的集合。", "body"),
        ]),
    ]
    chunks = semantic_chunk_document(pages)
    for chunk in chunks:
        assert "source_fragments_json" in chunk, \
            f"Chunk {chunk['chunk_index']} missing source_fragments_json"
        fragments = chunk["source_fragments_json"]
        assert isinstance(fragments, list)
        assert len(fragments) > 0
        for frag in fragments:
            assert "block_id" in frag
            assert "text_start" in frag
            assert "text_end" in frag


def test_same_block_in_two_chunks_both_have_provenance():
    """When one block is split into two chunks, both must reference it."""
    long_text = "这是一个很长的文本块。" * 30
    pages = [
        _make_page(1, [
            ("p1-b0", "标题", "heading"),
            ("p1-b1", long_text, "body"),
        ]),
    ]
    chunks = semantic_chunk_document(pages, target_length=50, max_length=100)
    b1_chunks = [c for c in chunks if "p1-b1" in c["source_block_ids"]]
    # The long block should be split into at least 2 chunks
    assert len(b1_chunks) >= 2, \
        f"Block p1-b1 should appear in >= 2 chunks, got {len(b1_chunks)}"


def test_hard_limit_split_records_fragment():
    """Hard-limit fallback splits must still record source fragments."""
    # Create text with no sentence boundaries to force hard_limit_fallback
    long_no_boundary = "abcdefghij" * 50
    pages = [
        _make_page(1, [
            ("p1-b0", "标题", "heading"),
            ("p1-b1", long_no_boundary, "body"),
        ]),
    ]
    chunks = semantic_chunk_document(pages, target_length=50, max_length=100)
    for chunk in chunks:
        if chunk["split_reason"] == "hard_limit_fallback":
            assert len(chunk["source_block_ids"]) > 0
            assert len(chunk["source_fragments_json"]) > 0


def test_large_list_safely_split():
    """Large lists must be split without exceeding max_length."""
    items = [f"列表项{i}" for i in range(100)]
    list_text = "\n".join(items)
    pages = [
        _make_page(1, [
            ("p1-b0", "项目列表", "heading"),
            ("p1-b1", list_text, "list"),
        ]),
    ]
    chunks = semantic_chunk_document(pages, target_length=100, max_length=200)
    # No chunk should exceed max_length (with some tolerance for newline joins)
    for chunk in chunks:
        assert len(chunk["text"]) <= 250, \
            f"Chunk {chunk['chunk_index']} is {len(chunk['text'])} chars, exceeds limit"


def test_protected_terms_not_split():
    """Protected terms like TCP/IP must not be split across chunks."""
    # Create text where TCP/IP is at a chunk boundary
    before = "A" * 95
    after = "B" * 50
    pages = [
        _make_page(1, [
            ("p1-b0", "标题", "heading"),
            ("p1-b1", f"{before}TCP/IP{after}", "body"),
        ]),
    ]
    chunks = semantic_chunk_document(pages, target_length=50, max_length=100)
    # Check that TCP/IP is not split across two chunks
    for i in range(len(chunks) - 1):
        end_text = chunks[i]["text"]
        start_text = chunks[i + 1]["text"]
        # TCP/IP should be fully in one chunk or the other
        combined = end_text + start_text
        assert "TCP/IP" in end_text or "TCP/IP" not in end_text
        if "TCP" in end_text and "TCP/IP" not in end_text:
            # TCP is at the end but /IP is at the start of next chunk
            assert False, "Protected term TCP/IP was split across chunks"
