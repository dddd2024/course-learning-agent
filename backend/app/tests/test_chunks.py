"""Tests for GET /api/v1/chunks/{chunk_id} (Phase 2 Task A).

Strict TDD: these tests are written first and fail until the
``chunks`` endpoint is implemented.

Covers:
- Owner can fetch chunk text + material metadata
- Cross-user access returns 404 (existence never leaked)
- Non-existent chunk_id returns 404
- Unauthenticated request returns 401
- Response includes chunk_id, material_id, material_name, title, page_no, text
"""
from app.tests.conftest import (
    auth_headers,
    setup_course_with_material,
)


TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
).encode("utf-8")


def _get_first_chunk_id(client, headers, course_id, material_id=None):
    """Retrieve the first chunk_id for a course.

    Uses the chunks list endpoint (or the chat endpoint as fallback) to
    obtain a valid chunk_id. The chat endpoint fallback may return empty
    citations in mock mode (EVID-V3-01), so the chunks endpoint is
    preferred when ``material_id`` is provided.
    """
    if material_id is not None:
        resp = client.get(
            f"/api/v1/materials/{material_id}/chunks",
            headers=headers,
        )
        if resp.status_code == 200:
            chunks = resp.json().get("chunks") or resp.json().get("items", [])
            if chunks:
                return chunks[0]["id"]

    # Fallback: ask a question and extract chunk_id from citations.
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]
    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200
    # EVID-V3-01: in mock mode all citations are "weak" and filtered out,
    # so fall back to retrieved_chunks which are always present.
    citations = chat_resp.json().get("citations", [])
    if citations:
        return citations[0]["chunk_id"]
    retrieved = chat_resp.json().get("retrieved_chunks", [])
    if retrieved:
        return retrieved[0]["chunk_id"]
    raise AssertionError("No chunks found via chat or chunks endpoint")


def test_get_chunk_owner(client, tmp_path, monkeypatch) -> None:
    """Owner can fetch a chunk with its text and material metadata."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers = auth_headers(client, username="alice")
    course_id, material_id = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )
    chunk_id = _get_first_chunk_id(client, headers, course_id, material_id)

    resp = client.get(f"/api/v1/chunks/{chunk_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunk_id"] == chunk_id
    assert "material_id" in body
    assert "material_name" in body
    assert "title" in body
    assert "page_no" in body
    assert "text" in body
    assert isinstance(body["text"], str)
    assert len(body["text"]) > 0


def test_get_chunk_cross_user_404(client, tmp_path, monkeypatch) -> None:
    """User B cannot access user A's chunk — returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers_a = auth_headers(client, username="alice")
    course_id, material_id = setup_course_with_material(
        client, headers_a, content=TLB_TEXT
    )
    chunk_id = _get_first_chunk_id(client, headers_a, course_id, material_id)

    headers_b = auth_headers(client, username="bob")
    resp = client.get(f"/api/v1/chunks/{chunk_id}", headers=headers_b)
    assert resp.status_code == 404


def test_get_chunk_not_found(client, tmp_path, monkeypatch) -> None:
    """Non-existent chunk_id returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/chunks/99999", headers=headers)
    assert resp.status_code == 404


def test_get_chunk_unauthenticated(client) -> None:
    """Unauthenticated request returns 401."""
    resp = client.get("/api/v1/chunks/1")
    assert resp.status_code == 401
