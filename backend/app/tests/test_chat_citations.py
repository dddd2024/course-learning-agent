"""Tests for citation deduplication (Phase 2 bugfix P1-1).

Ensures that when the LLM returns multiple citations pointing to the same
``chunk_id``, the backend deduplicates them so:
- The ChatResponse carries at most one citation per chunk_id.
- The persisted ``citations`` table has no duplicate chunk_id rows for a
  single message.
- The frontend never receives duplicate keys (which would trigger Vue
  duplicate-key warnings).
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


def _make_duplicate_citations(ranked):
    """Build an answer_question result with two citations sharing chunk_id."""
    top = ranked[0] if ranked else {"chunk_id": 1}
    quote = (top.get("text") or "")[:20]
    return {
        "answer": "快表是页表的高速缓存。",
        "key_points": ["加速地址转换"],
        "citations": [
            {
                "chunk_id": top["chunk_id"],
                "quote_text": quote,
                "reason": "原因 A",
                "confidence": 0.8,
            },
            {
                "chunk_id": top["chunk_id"],
                "quote_text": quote,
                "reason": "原因 B",
                "confidence": 0.6,
            },
        ],
        "not_found": False,
        "follow_up_questions": [],
        "retrieved_chunks": [],
        "reliability_level": "high",
    }


def test_chat_deduplicates_citations_with_same_chunk_id(
    client, tmp_path, monkeypatch
) -> None:
    """POST /chat must collapse duplicate chunk_id citations into one."""
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
        json={"course_id": course_id, "title": "去重测试"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]

    captured = {}

    def fake_answer(db, course_id, question, ranked, course_name, user_config=None):
        captured["ranked"] = ranked
        return _make_duplicate_citations(ranked)

    monkeypatch.setattr(
        "app.services.chat_service.answer_question", fake_answer
    )

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()

    # The response citations must have unique chunk_ids.
    chunk_ids = [c["chunk_id"] for c in body["citations"]]
    assert len(chunk_ids) == len(set(chunk_ids)), (
        f"expected unique chunk_ids, got {chunk_ids}"
    )
    # The duplicate should have collapsed to exactly one citation.
    assert len(body["citations"]) == 1

    # The persisted citations table must also be deduplicated.
    message_id = body["message_id"]
    cite_resp = client.get(
        f"/api/v1/messages/{message_id}/citations",
        headers=headers,
    )
    assert cite_resp.status_code == 200
    persisted = cite_resp.json()
    persisted_ids = [c["chunk_id"] for c in persisted["items"]]
    assert len(persisted_ids) == len(set(persisted_ids))
    assert len(persisted_ids) == 1
