"""V7.4.3-01 regression tests for strict chunk length and exact offsets."""
from __future__ import annotations

import random
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from app.retrieval.document_ir import DocumentBlock, DocumentPage
from app.retrieval.semantic_chunker import semantic_chunk, validate_chunk_provenance


def block(block_id: str, page: int, block_type: str, text: str) -> DocumentBlock:
    return DocumentBlock(block_id=block_id, page_no=page, block_type=block_type, reading_order=0, text=text)


def assert_valid(pages: list[DocumentPage], max_length: int) -> list[dict]:
    chunks = semantic_chunk(pages, target_length=max_length // 2, max_length=max_length)
    index = {item.block_id: item for page in pages for item in page.blocks}
    assert not validate_chunk_provenance(chunks, index)
    assert all(len(chunk["text"]) <= max_length for chunk in chunks)
    return chunks


def test_protected_boundary_moves_real_fragments_without_offset_scaling():
    # Split across two real blocks using terms that occur in course material.
    pages = [DocumentPage(page_no=1, blocks=[
        block("tcp", 1, "body", "A" * 47 + "TCP/"),
        block("ip", 1, "body", "IP" + "B" * 40 + " HTTP/2 " + "C" * 20),
        block("io", 1, "body", "I/O 与 Client/Server 和 B+树。"),
    ])]
    chunks = assert_valid(pages, 60)
    assert len(chunks) > 1


def test_long_list_table_and_cross_page_have_exact_character_provenance():
    table = "名称\t说明\n" + "\n".join(f"行{i}\t{'数据' * 12}" for i in range(20))
    pages = [
        DocumentPage(page_no=1, blocks=[
            block("list", 1, "list", "\n".join(f"{i}. {'CSMA/CD ' * 8}" for i in range(50))),
            block("table", 1, "table", table),
        ]),
        DocumentPage(page_no=2, blocks=[block("p2", 2, "body", "HTTP/2 " * 80)]),
    ]
    assert_valid(pages, 160)


def test_one_hundred_seeded_inputs_are_deterministic_and_never_overflow():
    for seed in range(100):
        rng = random.Random(seed)
        texts = []
        for index in range(1, 6):
            text = "".join(rng.choice(["TCP/IP ", "CSMA/CD ", "HTTP/2 ", "B+树 ", "I/O ", "Client/Server "]) for _ in range(30))
            texts.append(block(f"b{index}", 1, "body", text))
        pages = [DocumentPage(page_no=1, blocks=texts)]
        first = assert_valid(pages, 120)
        second = assert_valid(pages, 120)
        assert first == second
