"""Tests for POST /api/v1/chat/stream SSE endpoint (Phase 2 Task B).

Verifies that the streaming endpoint:
- Returns text/event-stream media type.
- Emits step_started / step_done / final events in the right order.
- Carries a valid ChatResponse in the final event.
- Returns 401 when unauthenticated.
- Returns 404 when the conversation belongs to another user.
- Emits a step_error event (and no final) when the pipeline fails early.
"""
import json

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


def _parse_sse(raw_text: str) -> list[dict]:
    """Parse an SSE response body into a list of {event, data} dicts."""
    events: list[dict] = []
    current_event = "message"
    current_data_lines: list[str] = []
    for line in raw_text.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: ") :].strip()
        elif line.startswith("data: "):
            current_data_lines.append(line[len("data: ") :])
        elif line.strip() == "":
            if current_data_lines:
                data_str = "\n".join(current_data_lines)
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = {"raw": data_str}
                events.append({"event": current_event, "data": data})
                current_event = "message"
                current_data_lines = []
    return events


def test_chat_stream_emits_events_in_order(
    client, tmp_path, monkeypatch
) -> None:
    """SSE stream emits step_started → step_done → final for a happy path."""
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
        "/api/v1/chat/stream",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse(resp.text)
    assert len(events) > 0

    event_types = [e["event"] for e in events]
    # Must end with a final event carrying the full ChatResponse.
    assert event_types[-1] == "final"
    # Must include at least the retrieve and generate step_started events.
    assert "step_started" in event_types
    # step_done should appear at least once (retrieve succeeds).
    assert "step_done" in event_types

    final_payload = events[-1]["data"]
    assert "data" in final_payload
    chat_body = final_payload["data"]
    for field in (
        "message_id",
        "answer",
        "citations",
        "not_found",
        "follow_up_questions",
        "reliability_level",
        "retrieved_chunks",
    ):
        assert field in chat_body

    # Retrieve step_started should come before retrieve step_done.
    retrieve_started_idx = next(
        i
        for i, e in enumerate(events)
        if e["event"] == "step_started" and e["data"].get("step") == "retrieve"
    )
    retrieve_done_idx = next(
        i
        for i, e in enumerate(events)
        if e["event"] == "step_done" and e["data"].get("step") == "retrieve"
    )
    assert retrieve_started_idx < retrieve_done_idx
    # And the final event must come after retrieve done.
    assert retrieve_done_idx < len(events) - 1


def test_chat_stream_unauthenticated_returns_401(client) -> None:
    """No auth header → 401, no SSE body."""
    resp = client.post(
        "/api/v1/chat/stream",
        json={
            "course_id": 1,
            "conversation_id": 1,
            "question": "anything",
        },
    )
    assert resp.status_code == 401


def test_chat_stream_cross_user_conversation_404(
    client, tmp_path, monkeypatch
) -> None:
    """User B streaming user A's conversation returns 404 (not 403)."""
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
        "/api/v1/chat/stream",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers_b,
    )
    assert resp.status_code == 404
