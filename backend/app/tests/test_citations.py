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
from app.agents.course_qa import answer_question, verify_citations
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
    # EVID-V3-01: mock call_llm_with_meta with degraded=False so citations
    # are not forced to "weak" status (which would be filtered out).
    from app.agents import course_qa as qa_module
    original_call_llm = qa_module.call_llm_with_meta

    def non_degraded_call_llm(prompt, agent_type, schema=None, user_config=None):
        output, meta = original_call_llm(
            prompt, agent_type, schema=schema, user_config=user_config
        )
        meta["degraded"] = False
        return output, meta

    monkeypatch.setattr(
        "app.agents.course_qa.call_llm_with_meta", non_degraded_call_llm
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


def test_unverified_citations_do_not_turn_into_fallback_evidence(monkeypatch) -> None:
    """Relevant retrieval is shown separately, never fabricated as a citation."""
    monkeypatch.setattr(
        "app.agents.course_qa.call_llm_with_meta",
        lambda *args, **kwargs: (
            {
                "answer": "模型给出的课程结论",
                "key_points": ["结论"],
                "citations": [{"chunk_id": 1, "quote_text": "伪造原文"}],
                "not_found": False,
                "follow_up_questions": ["追问"],
            },
            {"provider": "real", "fallback_used": False, "fallback_reason": None},
        ),
    )
    result = answer_question(
        db=None, course_id=1, question="问题", course_name="课程",
        retrieved_chunks=[{"chunk_id": 1, "text": "真实原文"}],
    )
    assert result["citations"] == []
    assert result["not_found"] is True
    assert "未能提供可验证" in result["answer"]


def test_not_found_flag_cannot_leak_an_uncited_partial_answer(monkeypatch) -> None:
    """A model's partial answer is hidden when no source citation survives."""
    monkeypatch.setattr(
        "app.agents.course_qa.call_llm_with_meta",
        lambda *args, **kwargs: (
            {
                "answer": "虚拟存储器会扩充可用内存。",
                "key_points": ["虚拟存储器"],
                "citations": [],
                "not_found": True,
                "follow_up_questions": [],
            },
            {"provider": "real", "fallback_used": False, "fallback_reason": None},
        ),
    )
    result = answer_question(
        db=None, course_id=1, question="问题", course_name="课程",
        retrieved_chunks=[{"chunk_id": 1, "text": "真实原文"}],
    )
    assert result["not_found"] is True
    assert result["citations"] == []
    assert "虚拟存储器会扩充" not in result["answer"]
    assert "未能提供可验证" in result["answer"]


def test_exact_quote_without_claim_is_marked_weak(monkeypatch) -> None:
    """Quote identity alone is not presented as verified claim support."""
    monkeypatch.setattr(
        "app.agents.course_qa.call_llm_with_meta",
        lambda *args, **kwargs: (
            {
                "answer": "快表加速地址转换。",
                "key_points": ["快表"],
                "citations": [{"chunk_id": 1, "quote_text": "快表加速地址转换"}],
                "not_found": False,
                "follow_up_questions": [],
            },
            {"provider": "real", "fallback_used": False, "fallback_reason": None},
        ),
    )
    result = answer_question(
        db=None, course_id=1, question="问题", course_name="课程",
        retrieved_chunks=[{"chunk_id": 1, "text": "快表加速地址转换"}],
    )
    assert result["citations"][0]["support_status"] == "weak"
    assert result["reliability_level"] == "low"


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
