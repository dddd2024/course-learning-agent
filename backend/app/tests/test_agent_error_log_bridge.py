"""Tests for the Agent error log bridge to the general ErrorLog table.

Covers Task C of the reliability-windows-launcher plan:
- When retrieve fails, an ErrorLog(category=agent) is written in addition
  to the legacy AgentErrorLog.
- When generate fails, an ErrorLog(category=agent) is written in addition
  to the legacy AgentErrorLog.
- The ErrorLog includes agent_run_id, course_id, and a user-facing title.
"""
from app.core.database import get_db
from app.models.error_log import AgentErrorLog
from app.models.general_error_log import ErrorLog
from app.tests.conftest import auth_headers
from app.tests.test_chat_stream import _parse_sse, _setup_chat, _test_db_session


def test_retrieve_failure_writes_general_error_log(
    client, tmp_path, monkeypatch
) -> None:
    """When keyword_search raises, an ErrorLog(category=agent) is written."""
    headers = auth_headers(client, username="alice")
    course_id, conversation_id = _setup_chat(
        client, headers, monkeypatch, tmp_path
    )

    def boom(*args, **kwargs):
        raise RuntimeError("retrieve exploded")

    monkeypatch.setattr("app.services.chat_service.keyword_search", boom)

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

    db = _test_db_session(client)
    try:
        # Legacy AgentErrorLog still written (backward compatibility).
        agent_log = (
            db.query(AgentErrorLog)
            .filter(AgentErrorLog.step == "retrieve")
            .first()
        )
        assert agent_log is not None

        # New general ErrorLog also written with category=agent.
        gen_log = (
            db.query(ErrorLog)
            .filter(ErrorLog.category == "agent")
            .first()
        )
        assert gen_log is not None
        assert gen_log.level == "error"
        assert gen_log.course_id == course_id
        assert gen_log.agent_run_id is not None
        assert "Agent" in gen_log.title or "agent" in gen_log.title.lower()
        assert "retrieve" in gen_log.message.lower() or "检索" in gen_log.message
    finally:
        db.close()

    # Also visible via the /logs API.
    logs = client.get("/api/v1/logs?category=agent", headers=headers).json()
    assert logs["total"] >= 1


def test_generate_failure_writes_general_error_log(
    client, tmp_path, monkeypatch
) -> None:
    """When answer_question raises, an ErrorLog(category=agent) is written."""
    headers = auth_headers(client, username="alice")
    course_id, conversation_id = _setup_chat(
        client, headers, monkeypatch, tmp_path
    )

    def boom(*args, **kwargs):
        raise RuntimeError("generate exploded")

    monkeypatch.setattr("app.services.chat_service.answer_question", boom)

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

    db = _test_db_session(client)
    try:
        # Legacy AgentErrorLog still written.
        agent_log = (
            db.query(AgentErrorLog)
            .filter(AgentErrorLog.step == "generate")
            .first()
        )
        assert agent_log is not None

        # New general ErrorLog also written.
        gen_log = (
            db.query(ErrorLog)
            .filter(ErrorLog.category == "agent")
            .first()
        )
        assert gen_log is not None
        assert gen_log.level == "error"
        assert gen_log.course_id == course_id
        assert gen_log.agent_run_id is not None
        assert "generate" in gen_log.message.lower() or "生成" in gen_log.message
    finally:
        db.close()
