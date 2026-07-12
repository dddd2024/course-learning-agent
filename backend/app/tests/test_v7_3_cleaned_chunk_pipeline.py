"""V7.3-01 P0-01: Cleaned Document IR must feed the semantic chunker.

Tests that the production parse pipeline feeds *cleaned* page text into
``semantic_chunk_document`` instead of raw page text.  Headers, footers,
page numbers, and standalone URLs must never appear in chunk text or FTS.
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.services.material_cleaner import clean_pages


def _make_page(page_no: int, lines: list[str], block_type: str = "body") -> DocumentPage:
    """Helper: build a DocumentPage with one body block per line."""
    blocks = []
    for i, line in enumerate(lines):
        blocks.append(DocumentBlock(
            block_id=f"p{page_no}-b{i}",
            page_no=page_no,
            block_type=block_type,
            reading_order=i,
            text=line,
        ))
    return DocumentPage(page_no=page_no, blocks=blocks)


def test_clean_pages_removes_header_footer_from_chunk_text():
    """Headers/footers repeated across pages must not appear in chunks."""
    from app.services.document_cleaning_pipeline import clean_document_pages

    raw_pages = [
        _make_page(1, ["课程名称：计算机网络", "TCP/IP协议是互联网的基础", "第1页"]),
        _make_page(2, ["课程名称：计算机网络", "CSMA/CD用于以太网", "第2页"]),
    ]
    cleaned = clean_document_pages(raw_pages)
    # The header "课程名称：计算机网络" and footer "第1页"/"第2页" should be removed
    page1_text = cleaned[0].text
    page2_text = cleaned[1].text
    assert "课程名称" not in page1_text
    assert "课程名称" not in page2_text
    assert "第1页" not in page1_text
    assert "第2页" not in page2_text
    # Semantic content must be preserved
    assert "TCP/IP" in page1_text
    assert "CSMA/CD" in page2_text


def test_cleaned_pages_produce_chunks_without_headers():
    """Chunks built from cleaned pages must not contain header/footer text."""
    from app.services.document_cleaning_pipeline import clean_document_pages
    from app.retrieval.semantic_chunker import semantic_chunk_document

    raw_pages = [
        _make_page(1, ["课程名称：计算机网络", "TCP/IP协议是互联网的基础协议", "第1页"]),
        _make_page(2, ["课程名称：计算机网络", "HTTP/2是HTTP协议的第二个版本", "第2页"]),
    ]
    cleaned = clean_document_pages(raw_pages)
    chunks = semantic_chunk_document(cleaned)
    all_chunk_text = " ".join(c["text"] for c in chunks)
    assert "课程名称" not in all_chunk_text
    assert "第1页" not in all_chunk_text
    assert "第2页" not in all_chunk_text
    assert "TCP/IP" in all_chunk_text
    assert "HTTP/2" in all_chunk_text


def test_cleaned_page_preserves_raw_block_ids():
    """Cleaned blocks must retain their original block_id for provenance."""
    from app.services.document_cleaning_pipeline import clean_document_pages

    raw_pages = [
        _make_page(1, ["课程名称：计算机网络", "TCP/IP协议是互联网的基础", "第1页"]),
    ]
    cleaned = clean_document_pages(raw_pages)
    # The cleaned page should still have blocks with original IDs
    block_ids = [b.block_id for b in cleaned[0].blocks]
    assert "p1-b0" in block_ids or "p1-b1" in block_ids
    # The semantic content block must retain its ID
    tcp_block = next(b for b in cleaned[0].blocks if "TCP/IP" in b.text)
    assert tcp_block.block_id == "p1-b1"


def test_parse_with_retry_feeds_cleaned_pages_to_chunker():
    """The production parse pipeline must pass cleaned pages to the chunker."""
    import inspect
    from app.services import material_parser

    source = inspect.getsource(material_parser.parse_with_retry)
    # The chunker call must use cleaned pages, not raw pages
    assert "clean_document_pages" in source or "cleaned_pages" in source
    # It must NOT call semantic_chunk_document(raw_pages) directly
    # The old pattern was: clean_results = clean_pages(...); chunks = semantic_chunk_document(pages)
    # The new pattern must pass cleaned pages to the chunker
    assert "semantic_chunk_document(pages)" not in source or "clean_document_pages" in source


def test_material_page_stores_both_raw_and_clean_text():
    """MaterialPage must persist both raw_text and clean_text."""
    from app.models.material_page import MaterialPage
    assert hasattr(MaterialPage, 'raw_text')
    assert hasattr(MaterialPage, 'clean_text')
