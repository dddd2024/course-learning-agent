"""V7 production parsing regression tests."""
from pathlib import Path

from app.retrieval.document_ir import DocumentPage
from app.retrieval.parsers import parse_file
from app.retrieval.semantic_chunker import semantic_chunk_document


def test_parse_file_returns_v7_document_ir_for_markdown(tmp_path: Path):
    path = tmp_path / "network.md"
    path.write_text("# TCP/IP\nHTTP/2 uses I/O.", encoding="utf-8")
    pages = parse_file(str(path), "md")
    assert isinstance(pages[0], DocumentPage)
    assert pages[0].parser_version == "layout-v7"
    assert pages[0].blocks and pages[0].blocks[0].block_id


def test_semantic_chunk_produces_required_provenance(tmp_path: Path):
    path = tmp_path / "network.txt"
    path.write_text("TCP/IP and CSMA/CD are networking concepts.", encoding="utf-8")
    chunks = semantic_chunk_document(parse_file(str(path), "txt"))
    assert chunks
    assert chunks[0]["chunker_version"] == "semantic-v7"
    assert chunks[0]["source_block_ids"]
    assert chunks[0]["page_start"] == chunks[0]["page_end"] == 1
