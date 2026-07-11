"""Tests for the citation module and CitationVerifier (BE-08, AG-04).

Strict TDD: these tests are written first and fail until the
``citations`` table, the GET /messages/{id}/citations endpoint,
and the citation persistence in POST /chat are implemented.

Covers:
- POST /chat persists citations to the citations table
- GET /api/v1/messages/{message_id}/citations returns the persisted list
- Cross-user access to a message's citations returns 404
- CitationVerifier drops citations whose chunk_id is not in retrieved chunks
- CitationVerifier keeps citations whose chunk_id is in retrieved chunks
- Out-of-material questions yield an empty citations list
"""
from app.agents.course_qa import verify_citations
from app.tests.conftest import (
    auth_headers,
    setup_course_with_material,
)


# Material content that mentions "快表 TLB" so keyword retrieval can
# surface relevant chunks for the "什么是快表？" question.
TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def test_citations_persisted_after_chat(
    client, tmp_path, monkeypatch
) -> None:
    """Citations returned by POST /chat are persisted and retrievable.

    Flow: upload + parse material → ask a question → GET the message's
    citations → each citation must carry chunk_id, quote_text,
    confidence, page_no, material_name.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

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
    message_id = chat_resp.json()["message_id"]

    cite_resp = client.get(
        f"/api/v1/messages/{message_id}/citations",
        headers=headers,
    )
    assert cite_resp.status_code == 200
    body = cite_resp.json()
    assert "items" in body
    assert body["total"] >= 1
    for item in body["items"]:
        assert "chunk_id" in item
        assert "quote_text" in item
        assert "confidence" in item
        assert "page_no" in item
        assert "material_name" in item


def test_citations_isolation(client, tmp_path, monkeypatch) -> None:
    """User B accessing user A's message citations returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers_a, content=TLB_TEXT
    )
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "A 的对话"},
        headers=headers_a,
    )
    conversation_id = conv_resp.json()["id"]

    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers_a,
    )
    message_id = chat_resp.json()["message_id"]

    headers_b = auth_headers(client, username="bob")
    resp = client.get(
        f"/api/v1/messages/{message_id}/citations",
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_citation_verifier_removes_invalid() -> None:
    """verify_citations drops citations whose chunk_id is not retrieved."""
    output = {
        "citations": [
            {
                "chunk_id": 999,  # not in retrieved_chunks
                "quote_text": "fabricated quote",
                "confidence": 0.9,
            },
            {
                "chunk_id": 1,  # valid
                "quote_text": "real quote",
                "confidence": 0.8,
            },
        ]
    }
    retrieved = [
        {"chunk_id": 1, "text": "real quote"},
        {"chunk_id": 2, "text": "another chunk"},
    ]
    kept = verify_citations(output, retrieved)
    chunk_ids = [c["chunk_id"] for c in kept]
    assert 999 not in chunk_ids
    assert 1 in chunk_ids
    assert len(kept) == 1


def test_citation_verifier_keeps_valid() -> None:
    """verify_citations keeps citations whose id and quote are retrieved."""
    output = {
        "citations": [
            {
                "chunk_id": 1,
                "quote_text": "first quote",
                "confidence": 0.8,
            },
            {
                "chunk_id": 2,
                "quote_text": "second quote",
                "confidence": 0.6,
            },
        ]
    }
    retrieved = [
        {"chunk_id": 1, "text": "first quote in a chunk"},
        {"chunk_id": 2, "text": "second quote in a chunk"},
        {"chunk_id": 3, "text": "unused chunk"},
    ]
    kept = verify_citations(output, retrieved)
    assert len(kept) == 2
    kept_ids = {c["chunk_id"] for c in kept}
    assert kept_ids == {1, 2}


def test_citation_verifier_removes_invalid_quote() -> None:
    """A valid chunk id cannot make an invented quote appear trustworthy."""
    output = {"citations": [{"chunk_id": 1, "quote_text": "invented quote"}]}
    assert verify_citations(output, [{"chunk_id": 1, "text": "actual source"}]) == []


def test_no_citations_when_not_found(
    client, tmp_path, monkeypatch
) -> None:
    """Asking outside the material leaves an empty citations list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "无关问题"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]

    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "量子力学",
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200
    message_id = chat_resp.json()["message_id"]

    cite_resp = client.get(
        f"/api/v1/messages/{message_id}/citations",
        headers=headers,
    )
    assert cite_resp.status_code == 200
    body = cite_resp.json()
    assert body["total"] == 0
    assert body["items"] == []
