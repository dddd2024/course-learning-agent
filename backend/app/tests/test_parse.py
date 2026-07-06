"""Tests for the material parsing and chunking module.

Strict TDD: these tests are written first and fail until the parse
endpoint, chunker, parsers, and MaterialChunk model are implemented.

Covers:
- POST /api/v1/materials/{id}/parse (txt, pdf, corrupt)
- GET  /api/v1/materials/{id}/chunks (paginated)
- 404 on non-existent material
- 404 on cross-user access
- Status transitions (uploaded -> processing -> ready/failed)
- Unit tests for chunk_text strategy and parsers
"""
import io

import pytest

from app.retrieval.chunker import (
    build_chunks,
    chunk_text,
    clean_keyword_text,
)
from app.retrieval.parsers import parse_pdf, parse_txt
from app.tests.conftest import auth_headers, create_course, upload_material


# A long Chinese paragraph (~3000 chars) used to exercise the chunker.
LONG_TEXT = (
    "操作系统是计算机系统中最基本的系统软件，"
    "它负责管理计算机的硬件资源和软件资源，"
    "为用户和应用程序提供一个方便的接口。"
    "操作系统的基本功能包括进程管理、内存管理、文件系统、设备管理和用户接口。"
    "进程管理负责创建、调度和销毁进程，保证多个进程公平地使用 CPU。"
    "内存管理负责分配和回收内存空间，提供虚拟内存机制。"
    "文件系统负责存储和管理文件，提供目录结构和访问控制。"
    "设备管理负责管理输入输出设备，为上层提供统一的接口。\n"
) * 30


def test_parse_txt_material(client, tmp_path, monkeypatch) -> None:
    """POST /materials/{id}/parse on a .txt returns ready + chunks."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client,
        headers,
        course_id,
        "notes.txt",
        LONG_TEXT.encode("utf-8"),
    )

    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert parse_resp.status_code == 200
    body = parse_resp.json()
    assert body["material_id"] == material_id
    assert body["status"] == "ready"
    assert body["chunk_count"] > 0

    chunks_resp = client.get(
        f"/api/v1/materials/{material_id}/chunks", headers=headers
    )
    assert chunks_resp.status_code == 200
    chunks_body = chunks_resp.json()
    items = chunks_body["items"] if isinstance(chunks_body, dict) else chunks_body
    assert len(items) > 0
    for chunk in items:
        assert "text" in chunk
        assert "chunk_index" in chunk


def test_parse_pdf_material(client, tmp_path, monkeypatch) -> None:
    """POST /materials/{id}/parse on a pypdf-generated PDF returns ready."""
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf not available")

    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    # Generate a minimal valid PDF (blank page) so the parser succeeds.
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_buffer = io.BytesIO()
    writer.write(pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "doc.pdf", pdf_bytes
    )

    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert parse_resp.status_code == 200
    assert parse_resp.json()["status"] == "ready"


def test_parse_invalid_material_id(client) -> None:
    """POST /materials/{id}/parse with unknown id returns 404."""
    headers = auth_headers(client, username="alice")
    response = client.post(
        "/api/v1/materials/99999/parse", headers=headers
    )
    assert response.status_code == 404


def test_parse_other_user_material(client, tmp_path, monkeypatch) -> None:
    """User B parsing user A's material returns 404 (isolation)."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id = create_course(client, headers_a, "操作系统")
    material_id = upload_material(
        client, headers_a, course_id, "notes.txt", b"hello world"
    )

    headers_b = auth_headers(client, username="bob")
    response = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers_b
    )
    assert response.status_code == 404


def test_chunks_pagination(client, tmp_path, monkeypatch) -> None:
    """GET /materials/{id}/chunks supports page/page_size pagination."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client,
        headers,
        course_id,
        "notes.txt",
        LONG_TEXT.encode("utf-8"),
    )
    client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)

    resp = client.get(
        f"/api/v1/materials/{material_id}/chunks?page=1&page_size=5",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert len(body["items"]) <= 5


def test_parse_failed_status(client, tmp_path, monkeypatch) -> None:
    """Parsing a corrupt file sets status=failed with error_message."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    # Upload bytes that look like a PDF by extension but are not a real PDF.
    material_id = upload_material(
        client, headers, course_id, "fake.pdf", b"not a real pdf"
    )

    response = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["chunk_count"] == 0

    # Verify the material row itself reflects the failure.
    list_resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    items = list_resp.json()["items"]
    mat = next(m for m in items if m["id"] == material_id)
    assert mat["status"] == "failed"
    assert mat["error_message"]


def test_chunk_size_strategy() -> None:
    """Unit test: chunk_text on long text produces overlapping chunks."""
    text = "操作系统" * 500  # 2000 chars
    chunks = chunk_text(text, chunk_size=600, overlap=100)
    assert len(chunks) > 1
    # Each non-final chunk should be in the 500-800 range (chunk_size=600).
    for chunk in chunks[:-1]:
        assert 500 <= len(chunk["text"]) <= 800
    # Overlap: the second chunk starts with the last 100 chars of the first.
    if len(chunks) >= 2:
        overlap_text = chunks[0]["text"][-100:]
        assert chunks[1]["text"].startswith(overlap_text)
    # Each chunk has the required fields and sequential indices.
    for i, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == i
        assert "text" in chunk
        assert "title" in chunk
        assert "page_no" in chunk


def test_parse_txt_unit(tmp_path) -> None:
    """parse_txt reads a UTF-8 text file."""
    path = tmp_path / "sample.txt"
    path.write_text("Hello 操作系统", encoding="utf-8")
    assert parse_txt(str(path)) == "Hello 操作系统"


def test_parse_pdf_unit(tmp_path) -> None:
    """parse_pdf returns [(page_no, text)] for a pypdf-generated PDF."""
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf not available")
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    pages = parse_pdf(str(path))
    assert isinstance(pages, list)
    assert len(pages) == 1
    page_no, text = pages[0]
    assert isinstance(page_no, int)
    assert isinstance(text, str)


def test_build_chunks_preserves_page_no() -> None:
    """build_chunks propagates page_no from parsed pages."""
    pages = [(1, "甲" * 1500), (2, "乙" * 200)]
    chunks = build_chunks(pages, chunk_size=600, overlap=100)
    assert len(chunks) > 0
    # All chunks carry a page_no from the originating page.
    for chunk in chunks:
        assert chunk["page_no"] in (1, 2)
    # Chunk indices are globally sequential.
    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_clean_keyword_text_basic() -> None:
    """clean_keyword_text collapses whitespace."""
    raw = "操作系统\n\n  进程  管理\t\n 内存管理"
    cleaned = clean_keyword_text(raw)
    assert "\n" not in cleaned
    assert "\t" not in cleaned
    assert "  " not in cleaned
    assert "操作系统" in cleaned
