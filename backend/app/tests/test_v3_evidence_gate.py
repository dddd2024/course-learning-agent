"""V3 Evidence Gate tests (BASE-V3-02).

These tests capture the audit blocker where chat citations with
``support_status="weak"`` are still shown as formal citations, and
where answers without verified citations are not replaced with an
"evidence insufficient" message.

Written to FAIL on the current codebase so the V3 fix plan can be
validated by turning these tests green.

Blockers captured:
- Weak citations pass through to the ChatResponse ``citations`` list.
- When all surviving citations are weak, the model's original answer is
  still returned instead of an evidence-insufficient placeholder.
"""
from app.tests.conftest import (
    auth_headers,
    setup_course_with_material,
)

TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def _weak_citation_result(ranked):
    """Build an answer_question result whose only citation is ``weak``."""
    top = ranked[0] if ranked else {"chunk_id": 1}
    quote = (top.get("text") or "")[:50]
    return {
        "answer": "快表是页表的高速缓存。",
        "key_points": ["加速地址转换"],
        "citations": [
            {
                "chunk_id": top["chunk_id"],
                "quote_text": quote,
                "claim_text": "快表是页表的高速缓存",
                "support_status": "weak",
                "verification_reason": "无法确认该引用支撑回答结论",
                "confidence": 0.3,
            },
        ],
        "not_found": False,
        "follow_up_questions": [],
        "retrieved_chunks": [],
        "reliability_level": "low",
        "provider": "mock",
        "fallback_used": False,
        "fallback_reason": None,
    }


def _verified_citation_result(ranked):
    """Build an answer_question result with one ``supported`` citation."""
    top = ranked[0] if ranked else {"chunk_id": 1}
    quote = (top.get("text") or "")[:50]
    return {
        "answer": "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。",
        "key_points": ["TLB加速地址转换"],
        "citations": [
            {
                "chunk_id": top["chunk_id"],
                "quote_text": quote,
                "claim_text": "快表 TLB 是页表的高速缓存",
                "support_status": "supported",
                "verification_reason": "原文精确匹配",
                "confidence": 0.85,
            },
        ],
        "not_found": False,
        "follow_up_questions": [],
        "retrieved_chunks": [],
        "reliability_level": "high",
        "provider": "mock",
        "fallback_used": False,
        "fallback_reason": None,
    }


def test_weak_citations_not_shown_as_formal(client, tmp_path, monkeypatch) -> None:
    """Citations with ``support_status='weak'`` must NOT appear in the response.

    The V3 evidence gate should filter out weak citations so the user is
    never presented with unverified claims as formal evidence.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "证据门测试"},
        headers=headers,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conversation_id = conv_resp.json()["id"]

    def fake_answer(db, course_id, question, ranked, course_name, user_config=None, **kwargs):
        return _weak_citation_result(ranked)

    monkeypatch.setattr("app.services.chat_service.answer_question", fake_answer)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Weak citations should NOT be in the formal citations list.
    weak_citations = [
        c for c in body["citations"] if c.get("support_status") == "weak"
    ]
    assert len(weak_citations) == 0, (
        f"Expected 0 weak citations in response, got {len(weak_citations)}: "
        f"{weak_citations}"
    )


def test_answer_replaced_when_only_weak_citations(client, tmp_path, monkeypatch) -> None:
    """When all surviving citations are weak, the answer must be replaced.

    The V3 evidence gate should replace the model's answer with an
    evidence-insufficient message when no verified citations survive.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "证据不足测试"},
        headers=headers,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conversation_id = conv_resp.json()["id"]

    def fake_answer(db, course_id, question, ranked, course_name, user_config=None, **kwargs):
        return _weak_citation_result(ranked)

    monkeypatch.setattr("app.services.chat_service.answer_question", fake_answer)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The answer should indicate evidence is insufficient.
    answer = body["answer"]
    assert (
        "证据" in answer
        or "evidence" in answer.lower()
        or "不足" in answer
        or "未验证" in answer
        or "无法确认" in answer
    ), f"Expected evidence-insufficient message, got: {answer}"

    # No formal citations should be returned when all are weak.
    assert len(body["citations"]) == 0, (
        f"Expected 0 citations when all are weak, got "
        f"{len(body['citations'])}"
    )


def test_verified_citations_pass_through_gate(client, tmp_path, monkeypatch) -> None:
    """Verified citations must still be shown after the evidence gate.

    Companion to the weak-filtering tests: the gate should only remove
    weak citations, not verified ones.  This serves as a regression
    guard so the V3 fix does not over-filter.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "验证引用测试"},
        headers=headers,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conversation_id = conv_resp.json()["id"]

    def fake_answer(db, course_id, question, ranked, course_name, user_config=None, **kwargs):
        return _verified_citation_result(ranked)

    monkeypatch.setattr("app.services.chat_service.answer_question", fake_answer)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    verified = [
        c for c in body["citations"] if c.get("support_status") == "supported"
    ]
    assert len(verified) >= 1, (
        f"Expected at least 1 supported citation, got {len(verified)}: "
        f"{body['citations']}"
    )
