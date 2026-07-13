"""Production-path regressions for V7.4.4-01 provenance contracts."""
from __future__ import annotations

import pytest
import random

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import (
    _PROTECTED_TERMS,
    _is_protected_at_boundary,
    semantic_chunk_document,
    validate_chunk_provenance,
)


def make_block(block_id: str, text: str, *, block_type: str = "body", page_no: int = 1) -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id,
        page_no=page_no,
        block_type=block_type,
        reading_order=0,
        text=text,
    )


def chunk_pages(pages: list[DocumentPage], max_length: int) -> list[dict]:
    chunks = semantic_chunk_document(
        pages, target_length=max_length // 2, max_length=max_length,
    )
    block_index = {
        block.block_id: block
        for page in pages
        for block in page.blocks
    }
    assert not validate_chunk_provenance(chunks, block_index, max_length=max_length)
    assert all(len(chunk["text"]) <= max_length for chunk in chunks)
    for previous, current in zip(chunks, chunks[1:]):
        assert not _is_protected_at_boundary(previous["text"], current["text"])
    return chunks


@pytest.mark.parametrize("term", _PROTECTED_TERMS)
def test_protected_term_boundary_relocation_preserves_provenance(term: str) -> None:
    split_at = max(1, len(term) // 2)
    pages = [DocumentPage(page_no=1, blocks=[
        make_block("left", "A" * 30 + term[:split_at]),
        make_block("right", term[split_at:] + "B" * 30),
    ])]

    chunks = chunk_pages(pages, max_length=40)

    assert any(term in chunk["text"] for chunk in chunks)


def test_max_length_smaller_than_protected_term_fails_closed() -> None:
    pages = [DocumentPage(page_no=1, blocks=[make_block("body", "ordinary text")])]

    with pytest.raises(ValueError, match="protected terms"):
        semantic_chunk_document(pages, max_length=3)


def test_long_header_uses_absolute_source_offsets_across_duplicate_table_blocks() -> None:
    header = "重复表头" * 18
    pages = [DocumentPage(page_no=1, blocks=[
        make_block("header", header, block_type="table"),
        make_block("row-a", "重复文本\t第一行数据", block_type="table"),
        make_block("row-b", "重复文本\t第二行数据", block_type="table"),
    ])]

    chunks = chunk_pages(pages, max_length=40)
    fragment_ids = {
        fragment["block_id"]
        for chunk in chunks
        for fragment in chunk["source_fragments_json"]
    }

    assert {"header", "row-a", "row-b"} <= fragment_ids


def test_provenance_output_is_deterministic_for_long_header_and_protected_terms() -> None:
    pages = [DocumentPage(page_no=1, blocks=[
        make_block("table-header", "列" * 120, block_type="table"),
        make_block("table-row", ("TCP/IP " * 20).strip(), block_type="table"),
        make_block("body", ("Client/Server 与 CSMA/CD。" * 12)),
    ])]

    first = chunk_pages(pages, max_length=90)
    for _ in range(19):
        assert chunk_pages(pages, max_length=90) == first


def test_one_hundred_seeded_inputs_repeat_twenty_times_without_term_splits() -> None:
    for seed in range(100):
        rng = random.Random(seed)
        pages = [DocumentPage(page_no=1, blocks=[
            make_block(
                f"seed-{seed}-{block_index}",
                "".join(rng.choice([*(_PROTECTED_TERMS), "正文", "。", " "]) for _ in range(40)),
            )
            for block_index in range(4)
        ])]
        first = chunk_pages(pages, max_length=120)
        for _ in range(19):
            assert chunk_pages(pages, max_length=120) == first
