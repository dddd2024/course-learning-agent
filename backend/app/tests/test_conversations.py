"""Tests for conversation history endpoint (T04: 两次审计问题整改).

Covers:
- GET /api/v1/conversations/{id}/messages returns user/assistant messages
- Cross-user isolation: user B cannot read user A's conversation messages
- History replay includes citations bound to assistant messages
"""
from app.tests.conftest import auth_headers, create_course, setup_course_with_material


TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def test_list_messages_returns_history(client, tmp_path, monkeypatch) -> None:
    """GET /conversations/{id}/messages returns user+assistant messages in order."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "历史回放"},
        headers=headers,
    )
    conv_id = conv_resp.json()["id"]

    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conv_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200

    hist = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers)
    assert hist.status_code == 200
    body = hist.json()
    assert "items" in body
    assert "total" in body
    items = body["items"]
    assert len(items) >= 2
    assert items[0]["role"] == "user"
    assert "快表" in items[0]["content"]
    assert items[1]["role"] == "assistant"
    # assistant 消息应携带 citations（来自 mock LLM，检索命中 TLB chunk）
    assert "citations" in items[1]
    assert isinstance(items[1]["citations"], list)


def test_list_messages_404_for_other_user(client, tmp_path, monkeypatch) -> None:
    """User B reading user A's conversation messages returns 404."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers_a = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers_a, content=TLB_TEXT)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "A 私有"},
        headers=headers_a,
    )
    conv_id = conv_resp.json()["id"]

    headers_b = auth_headers(client, username="bob")
    hist = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers_b)
    assert hist.status_code == 404


def test_list_messages_empty_for_new_conversation(client, tmp_path, monkeypatch) -> None:
    """A freshly created conversation with no chat returns empty items list."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "空课程")
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "空对话"},
        headers=headers,
    )
    conv_id = conv_resp.json()["id"]

    hist = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers)
    assert hist.status_code == 200
    assert hist.json()["items"] == []
    assert hist.json()["total"] == 0
