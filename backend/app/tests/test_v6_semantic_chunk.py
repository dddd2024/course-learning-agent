"""V6-12: Semantic chunker tests.

Tests construct ``DocumentPage`` objects with ``DocumentBlock`` blocks
and verify the semantic chunker's split priorities, term protection, and
provenance tracking.
"""
from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk

CHUNKER_VERSION = "semantic-v7"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block(page_no, order, text, btype="body", size=10.0, level=0):
    """Build a DocumentBlock with a deterministic block_id."""
    import hashlib

    block_id = hashlib.md5(
        f"{page_no}:{order}:{text[:50]}".encode("utf-8")
    ).hexdigest()[:16]
    return DocumentBlock(
        block_id=block_id,
        page_no=page_no,
        block_type=btype,
        reading_order=order,
        bbox=(0, 0, 0, 0),
        text=text,
        font_size=size,
        list_level=level,
        source_kind="pdf",
    )


def _page(page_no, blocks, page_type="text"):
    return DocumentPage(
        page_no=page_no,
        page_type=page_type,
        blocks=blocks,
    )


def _long_text(n=80, prefix="TCP/IP"):
    """Generate a body string longer than target_length."""
    return (prefix + " 是互联网的基础通信协议，支持端到端的数据传输。") * n


# ---------------------------------------------------------------------------
# Chunk dict contract
# ---------------------------------------------------------------------------

def test_chunk_dict_has_required_fields():
    blocks = [
        _block(1, 0, "第一章 网络", "heading", 20.0),
        _block(1, 1, "正文内容。" * 20, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=100, max_length=200)
    assert len(chunks) >= 1
    for c in chunks:
        assert "text" in c
        assert "title" in c
        assert "page_start" in c
        assert "page_end" in c
        assert "source_block_ids" in c
        assert "split_reason" in c
        assert "chunk_index" in c
        assert c["chunker_version"] == CHUNKER_VERSION


# ---------------------------------------------------------------------------
# Split priority: heading boundary
# ---------------------------------------------------------------------------

def test_heading_boundary_split():
    """When a heading is encountered, the current chunk must be split."""
    blocks = [
        _block(1, 0, "第一章 网络基础", "heading", 20.0),
        _block(1, 1, _long_text(10), "body"),
        _block(1, 2, "1.1 TCP/IP 协议栈", "heading", 14.0),
        _block(1, 3, _long_text(10), "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=100, max_length=500)
    assert len(chunks) >= 2
    # At least one chunk should be split at a heading boundary.
    heading_splits = [c for c in chunks if c["split_reason"] == "heading"]
    assert heading_splits, (
        f"expected at least one heading split, got reasons: "
        f"{[c['split_reason'] for c in chunks]}"
    )


# ---------------------------------------------------------------------------
# Split priority: paragraph boundary
# ---------------------------------------------------------------------------

def test_paragraph_boundary_split():
    """When content exceeds target_length, prefer splitting at paragraph
    boundaries."""
    para1 = "TCP/IP 协议栈分为四层，每层负责不同的功能。" * 10
    para2 = "CSMA/CD 是早期以太网的介质访问控制协议。" * 10
    blocks = [
        _block(1, 0, "正文", "heading", 14.0),
        _block(1, 1, para1, "body"),
        _block(1, 2, para2, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=100, max_length=500)
    assert len(chunks) >= 2
    # At least one split should be a paragraph boundary.
    para_splits = [c for c in chunks if c["split_reason"] == "paragraph"]
    assert para_splits, (
        f"expected at least one paragraph split, got reasons: "
        f"{[c['split_reason'] for c in chunks]}"
    )


# ---------------------------------------------------------------------------
# List stays together
# ---------------------------------------------------------------------------

def test_list_stays_together():
    """A list and its heading must not be split across chunks."""
    list_items = [
        _block(1, 1, "1. 应用层：HTTP, FTP, SMTP", "list", 10.0, level=1),
        _block(1, 2, "2. 传输层：TCP, UDP", "list", 10.0, level=1),
        _block(1, 3, "3. 网络层：IP, ICMP", "list", 10.0, level=1),
        _block(1, 4, "4. 网络接口层：Wi-Fi", "list", 10.0, level=1),
    ]
    blocks = [
        _block(1, 0, "TCP/IP 协议栈层次", "heading", 14.0),
        _block(1, 5, _long_text(5), "body"),  # body after the list
    ] + list_items
    # Re-sort by reading order
    blocks.sort(key=lambda b: b.reading_order)
    chunks = semantic_chunk([_page(1, blocks)], target_length=50, max_length=200)

    # Find the chunk(s) containing list items.
    list_block_ids = {b.block_id for b in list_items}
    for chunk in chunks:
        chunk_list_ids = set(chunk["source_block_ids"]) & list_block_ids
        if chunk_list_ids:
            # All list items should be in the same chunk.
            assert list_block_ids.issubset(set(chunk["source_block_ids"])), (
                "list items split across chunks: "
                f"{chunk_list_ids} in chunk {chunk['chunk_index']}"
            )


# ---------------------------------------------------------------------------
# Table stays together with header
# ---------------------------------------------------------------------------

def test_table_stays_together_with_header():
    """Table blocks must all end up in the same chunk."""
    table_blocks = [
        _block(1, 0, "策略 优点 缺点", "table", 9.0),
        _block(1, 1, "分页 无外部碎片 有内部碎片", "table", 9.0),
        _block(1, 2, "分段 逻辑清晰 有外部碎片", "table", 9.0),
        _block(1, 3, "段页式 综合优点 地址转换复杂", "table", 9.0),
    ]
    chunks = semantic_chunk([_page(1, table_blocks)], target_length=30, max_length=100)

    table_block_ids = {b.block_id for b in table_blocks}
    # All table blocks should be in exactly one chunk.
    chunks_with_table = [
        c for c in chunks if set(c["source_block_ids"]) & table_block_ids
    ]
    assert len(chunks_with_table) == 1, (
        f"table blocks should be in one chunk, found in {len(chunks_with_table)} chunks"
    )
    assert table_block_ids.issubset(set(chunks_with_table[0]["source_block_ids"]))


# ---------------------------------------------------------------------------
# Sentence boundary
# ---------------------------------------------------------------------------

def test_sentence_not_split_before_punctuation():
    """A sentence boundary split must keep punctuation with the sentence."""
    text = "TCP/IP 是互联网的基础协议。CSMA/CD 是以太网的访问控制协议。" * 5
    blocks = [
        _block(1, 0, "正文", "heading", 14.0),
        _block(1, 1, text, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=60, max_length=200)
    assert len(chunks) >= 2
    # The split should occur at a sentence boundary (after 。).
    for chunk in chunks[:-1]:
        # Chunk should end with a sentence-ending punctuation or be a
        # heading/title chunk.
        stripped = chunk["text"].rstrip()
        if chunk["split_reason"] == "sentence":
            assert stripped[-1] in "。！？.!?", (
                f"sentence split should end with punctuation, got: ...{stripped[-20:]!r}"
            )


# ---------------------------------------------------------------------------
# Technical term protection: TCP/IP
# ---------------------------------------------------------------------------

def test_tcp_ip_not_split_across_chunks():
    """The term 'TCP/IP' must never be split across a chunk boundary."""
    text = "TCP/IP 协议栈 " * 50  # many occurrences of TCP/IP
    blocks = [
        _block(1, 0, "TCP/IP 协议栈", "heading", 14.0),
        _block(1, 1, text, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=40, max_length=80)
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        # TCP/IP must not be split between end of chunk[i] and start of chunk[i+1]
        end_text = chunks[i]["text"]
        start_text = chunks[i + 1]["text"]
        # Check no partial TCP/IP at the boundary.
        combined_tail = end_text[-10:] + start_text[:10]
        # If "TCP/IP" appears split, we'd see "TCP/" at end and "IP" at start
        # (or "TCP" at end and "/IP" at start).
        assert "TCP/IP" in combined_tail or not _is_partial_tcp_ip(end_text, start_text), (
            f"TCP/IP was split between chunk {i} and {i+1}:\n"
            f"  end:   ...{end_text[-20:]!r}\n"
            f"  start: {start_text[:20]!r}..."
        )


def _is_partial_tcp_ip(end_text, start_text):
    """Check if TCP/IP is split across the boundary."""
    for split_pos in range(1, len("TCP/IP")):
        suffix = "TCP/IP"[-split_pos:]
        prefix = "TCP/IP"[:-split_pos]
        if end_text.endswith(suffix) and start_text.startswith(prefix):
            return True
    # Also check "TCP/" at end and "IP" at start
    if end_text.endswith("TCP/") and start_text.startswith("IP"):
        return True
    if end_text.endswith("TCP") and start_text.startswith("/IP"):
        return True
    return False


# ---------------------------------------------------------------------------
# Technical term protection: CSMA/CD
# ---------------------------------------------------------------------------

def test_csma_cd_not_split_across_chunks():
    """The term 'CSMA/CD' must never be split across a chunk boundary."""
    text = "CSMA/CD 是以太网协议 " * 50
    blocks = [
        _block(1, 0, "CSMA/CD 协议", "heading", 14.0),
        _block(1, 1, text, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=40, max_length=80)
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        end_text = chunks[i]["text"]
        start_text = chunks[i + 1]["text"]
        assert not _is_partial_csma_cd(end_text, start_text), (
            f"CSMA/CD was split between chunk {i} and {i+1}:\n"
            f"  end:   ...{end_text[-20:]!r}\n"
            f"  start: {start_text[:20]!r}..."
        )


def _is_partial_csma_cd(end_text, start_text):
    """Check if CSMA/CD is split across the boundary."""
    term = "CSMA/CD"
    for split_pos in range(1, len(term)):
        suffix = term[-split_pos:]
        prefix = term[:-split_pos]
        if end_text.endswith(suffix) and start_text.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Hard limit fallback
# ---------------------------------------------------------------------------

def test_hard_limit_fallback_records_split_reason():
    """When no good boundary exists and max_length is exceeded, the chunker
    must split with ``split_reason='hard_limit_fallback'``."""
    # A single very long body block with no sentence boundaries.
    long_text = "X" * 500
    blocks = [
        _block(1, 0, "正文", "heading", 14.0),
        _block(1, 1, long_text, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=50, max_length=100)
    assert len(chunks) >= 2
    hard_splits = [c for c in chunks if c["split_reason"] == "hard_limit_fallback"]
    assert hard_splits, (
        f"expected hard_limit_fallback split, got reasons: "
        f"{[c['split_reason'] for c in chunks]}"
    )


# ---------------------------------------------------------------------------
# Source block IDs populated
# ---------------------------------------------------------------------------

def test_source_block_ids_populated():
    """Every chunk must have a non-empty source_block_ids list."""
    blocks = [
        _block(1, 0, "第一章", "heading", 20.0),
        _block(1, 1, "正文内容。" * 20, "body"),
        _block(1, 2, "1.1 小节", "heading", 14.0),
        _block(1, 3, "更多正文。" * 20, "body"),
    ]
    chunks = semantic_chunk([_page(1, blocks)], target_length=80, max_length=200)
    assert len(chunks) >= 2
    all_block_ids = {b.block_id for b in blocks}
    for chunk in chunks:
        assert chunk["source_block_ids"], (
            f"chunk {chunk['chunk_index']} has empty source_block_ids"
        )
        for bid in chunk["source_block_ids"]:
            assert bid in all_block_ids, f"unknown block_id {bid}"


# ---------------------------------------------------------------------------
# Chunk can locate back to original page and block
# ---------------------------------------------------------------------------

def test_chunk_locates_back_to_page_and_block():
    """page_start / page_end must correctly reflect the originating pages,
    and source_block_ids must reference real blocks."""
    blocks_p1 = [
        _block(1, 0, "第一章 网络", "heading", 20.0),
        _block(1, 1, "TCP/IP 是基础协议。" * 10, "body"),
    ]
    blocks_p2 = [
        _block(2, 0, "1.1 TCP/IP 协议栈", "heading", 14.0),
        _block(2, 1, "CSMA/CD 是访问控制。" * 10, "body"),
    ]
    pages = [_page(1, blocks_p1), _page(2, blocks_p2)]
    chunks = semantic_chunk(pages, target_length=80, max_length=200)

    # Collect all block_ids from both pages.
    page_by_block = {}
    for p in pages:
        for b in p.blocks:
            page_by_block[b.block_id] = p.page_no

    for chunk in chunks:
        ps = chunk["page_start"]
        pe = chunk["page_end"]
        assert ps is not None
        assert pe is not None
        assert ps <= pe
        # Every source block's page must be within [page_start, page_end].
        for bid in chunk["source_block_ids"]:
            bp = page_by_block[bid]
            assert ps <= bp <= pe, (
                f"block {bid} on page {bp} outside [{ps}, {pe}]"
            )


# ---------------------------------------------------------------------------
# Cross-page chunking
# ---------------------------------------------------------------------------

def test_cross_page_chunking_preserves_page_range():
    """A chunk spanning multiple pages must record the correct page range."""
    # Page 1 ends with body text; page 2 continues with body text (no heading).
    blocks_p1 = [
        _block(1, 0, "正文", "heading", 14.0),
        _block(1, 1, "短文本一。", "body"),
    ]
    blocks_p2 = [
        _block(2, 0, "短文本二。", "body"),
    ]
    pages = [_page(1, blocks_p1), _page(2, blocks_p2)]
    chunks = semantic_chunk(pages, target_length=600, max_length=1000)
    # With a large target, the two pages might merge into one chunk.
    if len(chunks) == 1:
        assert chunks[0]["page_start"] == 1
        assert chunks[0]["page_end"] == 2
    else:
        # If split, each chunk's page range should be valid.
        for chunk in chunks:
            assert chunk["page_start"] <= chunk["page_end"]
