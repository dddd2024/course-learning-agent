"""Tests for the chat module and CourseQAAgent (BE-07, AG-03).

Strict TDD: these tests are written first and fail until the
conversations router, chat endpoint, Conversation/Message models,
and CourseQAAgent are implemented.

Covers:
- POST /api/v1/conversations (create)
- GET  /api/v1/conversations?course_id=X (list, user-scoped)
- POST /api/v1/chat (answer question over material)
- Chat isolation (cross-user 404)
- CourseQAAgent output schema
- Citations bind to retrieved chunks
"""
from sqlalchemy.orm import Session

from app.agents.course_qa import answer_question
from app.api.deps import get_db
from app.main import app
from app.tests.conftest import (
    auth_headers,
    create_course,
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


def test_create_conversation(client, tmp_path, monkeypatch) -> None:
    """POST /api/v1/conversations returns 201 with id/course_id/title."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["course_id"] == course_id
    assert body["title"] == "TLB 答疑"


def test_list_conversations(client, tmp_path, monkeypatch) -> None:
    """GET /api/v1/conversations?course_id=X returns the user's conversations."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")

    for title in ("对话一", "对话二"):
        client.post(
            "/api/v1/conversations",
            json={"course_id": course_id, "title": title},
            headers=headers,
        )

    resp = client.get(
        f"/api/v1/conversations?course_id={course_id}",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    items = body["items"] if isinstance(body, dict) else body
    assert len(items) == 2


def test_chat_with_material(client, tmp_path, monkeypatch) -> None:
    """POST /api/v1/chat returns 200 with answer and non-empty citations."""
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
    assert "message_id" in body
    assert "answer" in body
    assert "citations" in body
    assert len(body["citations"]) >= 1
    assert "agent_run_id" in body


def test_chat_response_exposes_provider_and_fallback(client, tmp_path, monkeypatch) -> None:
    """T05: ChatResponse carries provider/fallback_used/fallback_reason.

    In mock mode provider is "mock" and fallback_used is False.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "fallback test"},
        headers=headers,
    )
    conv_id = conv_resp.json()["id"]

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "provider" in body
    assert "fallback_used" in body
    assert "fallback_reason" in body
    # mock mode → provider "mock", fallback_used False
    assert body["provider"] == "mock"
    assert body["fallback_used"] is False


def test_chat_not_found(client, tmp_path, monkeypatch) -> None:
    """Asking a question outside the material yields not_found / empty citations."""
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

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "量子力学",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # Either not_found is true or citations is empty — no fabricated citations.
    assert body["not_found"] is True or len(body["citations"]) == 0


def test_chat_isolation(client, tmp_path, monkeypatch) -> None:
    """User B posting chat in user A's conversation returns 404."""
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

    headers_b = auth_headers(client, username="bob")
    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_answer_json_schema(client, tmp_path, monkeypatch) -> None:
    """Unit test: CourseQAAgent output has all required fields."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        retrieved = [
            {
                "chunk_id": 1,
                "text": "快表 TLB 是页表的高速缓存。",
                "score": 3,
                "page_no": 1,
                "material_id": 1,
                "filename": "notes.txt",
                "title": None,
            }
        ]
        result = answer_question(
            db, course_id, "什么是快表？", retrieved, "操作系统"
        )
        for field in (
            "answer",
            "key_points",
            "citations",
            "not_found",
            "follow_up_questions",
        ):
            assert field in result
        assert isinstance(result["answer"], str)
        assert isinstance(result["key_points"], list)
        assert isinstance(result["citations"], list)
        assert isinstance(result["not_found"], bool)
        assert isinstance(result["follow_up_questions"], list)
    finally:
        db.close()


def test_citations_bind_to_chunks(client, tmp_path, monkeypatch) -> None:
    """Citations' chunk_id must come from retrieved_chunks."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(
        client, headers, content=TLB_TEXT
    )

    db_generator = app.dependency_overrides[get_db]()
    db: Session = next(db_generator)
    try:
        retrieved = [
            {
                "chunk_id": 10,
                "text": "快表 TLB 是页表的高速缓存。",
                "score": 3,
                "page_no": 1,
                "material_id": 1,
                "filename": "notes.txt",
                "title": None,
            },
            {
                "chunk_id": 20,
                "text": "TLB 命中时无需访问页表。",
                "score": 2,
                "page_no": 1,
                "material_id": 1,
                "filename": "notes.txt",
                "title": None,
            },
        ]
        result = answer_question(
            db, course_id, "什么是快表？", retrieved, "操作系统"
        )
        valid_ids = {c["chunk_id"] for c in retrieved}
        for cite in result["citations"]:
            assert cite["chunk_id"] in valid_ids
    finally:
        db.close()
