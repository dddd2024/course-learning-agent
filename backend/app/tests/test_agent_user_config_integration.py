"""Integration tests for Task 5 — Agent layer + endpoints user config.

Strict TDD: these tests are written first and fail until the agents
accept ``user_config`` and the endpoints read the active config before
calling the agent.

Covers:
- chat uses user_config when an active config exists
- chat falls back to mock when no config exists
- audit records provider='user' / config_id when a config is active
- audit records provider='mock' when no config exists
- knowledge_points generation uses user_config
- quiz generation uses user_config
"""
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app
from app.models.audit import AgentRun
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

PLAINTEXT_KEY = "sk-integration-1234567890"

LLM_CONFIG_PAYLOAD = {
    "provider": "openai",
    "name": "my-openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key": PLAINTEXT_KEY,
    "temperature": 0.2,
    "max_tokens": 2000,
    "timeout_seconds": 60,
}


def _create_and_enable_config(client, headers) -> int:
    """Create a user LLM config, enable it as default, return its id."""
    resp = client.post(
        "/api/v1/llm-configs",
        json=LLM_CONFIG_PAYLOAD,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    config_id = resp.json()["id"]
    enable_resp = client.post(
        f"/api/v1/llm-configs/{config_id}/enable", headers=headers
    )
    assert enable_resp.status_code == 200
    return config_id


def _get_db_session() -> Session:
    """Return a session from the test DB override."""
    db_generator = app.dependency_overrides[get_db]()
    return next(db_generator)


def _extract_user_config(call_args) -> dict:
    """Pull the user_config dict from a _real_response mock call."""
    if len(call_args.args) >= 4:
        return call_args.args[3]
    return call_args.kwargs.get("user_config")


def _course_qa_response() -> dict:
    """Valid course_qa response for the mocked real provider."""
    return {
        "answer": "user-config answer",
        "key_points": ["point"],
        "citations": [
            {
                "chunk_id": "chunk_1",
                "quote_text": "...",
                "reason": "...",
                "confidence": 0.9,
            }
        ],
        "not_found": False,
        "follow_up_questions": ["q1"],
    }


def _outline_response() -> dict:
    """Valid outline response for the mocked real provider."""
    return {
        "knowledge_points": [
            {
                "title": "知识点1",
                "summary": "...",
                "importance": 3,
                "source_chunk_ids": ["chunk_1"],
                "exam_style": "简答题",
                "review_action": "复习",
            }
        ]
    }


def _quiz_response() -> dict:
    """Valid quiz_generate response for the mocked real provider."""
    return {
        "questions": [
            {
                "question_type": "single_choice",
                "stem": "题干",
                "options": ["A", "B"],
                "answer": "A",
                "explanation": "...",
                "knowledge_point_ids": ["kp_1"],
            }
        ]
    }


# ---------------------------------------------------------------------------
# chat: uses user_config when an active config exists
# ---------------------------------------------------------------------------


def test_chat_uses_user_config_when_active(
    client, tmp_path, monkeypatch
) -> None:
    """With an active user config, chat calls _real_response with it."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    _create_and_enable_config(client, headers)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]

    with patch(
        "app.agents.llm._real_response",
        return_value=_course_qa_response(),
    ) as mock_real:
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
    mock_real.assert_called_once()
    user_config = _extract_user_config(mock_real.call_args)
    assert user_config is not None
    assert user_config["base_url"] == LLM_CONFIG_PAYLOAD["base_url"]
    assert user_config["model"] == LLM_CONFIG_PAYLOAD["model"]
    assert user_config["api_key"] == PLAINTEXT_KEY


# ---------------------------------------------------------------------------
# chat: falls back to mock without a config
# ---------------------------------------------------------------------------


def test_chat_falls_back_to_mock_without_config(
    client, tmp_path, monkeypatch
) -> None:
    """No user config + mock provider: chat works, _real_response not called."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "mock")

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]

    with patch(
        "app.agents.llm._real_response",
        side_effect=AssertionError(
            "should not call _real_response in mock mode without user_config"
        ),
    ):
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
    assert "answer" in body


# ---------------------------------------------------------------------------
# chat: audit records provider='user' when a config is active
# ---------------------------------------------------------------------------


def test_chat_audit_records_provider_user(
    client, tmp_path, monkeypatch
) -> None:
    """With active config, agent_run.provider='user', config_id=config.id."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    config_id = _create_and_enable_config(client, headers)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "TLB 答疑"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]

    with patch(
        "app.agents.llm._real_response",
        return_value=_course_qa_response(),
    ):
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
    run_id = resp.json()["agent_run_id"]
    db = _get_db_session()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        assert run is not None
        assert run.provider == "user"
        assert run.config_id == config_id
        assert run.model_name == LLM_CONFIG_PAYLOAD["model"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# chat: audit records provider='mock' without a config
# ---------------------------------------------------------------------------


def test_chat_audit_records_provider_mock(
    client, tmp_path, monkeypatch
) -> None:
    """No config: agent_run.provider='mock', config_id=None."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "mock")

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

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

    assert resp.status_code == 200, resp.text
    run_id = resp.json()["agent_run_id"]
    db = _get_db_session()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        assert run is not None
        assert run.provider == "mock"
        assert run.config_id is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# knowledge_points: uses user_config when an active config exists
# ---------------------------------------------------------------------------


def test_knowledge_points_uses_user_config(
    client, tmp_path, monkeypatch
) -> None:
    """With active config, knowledge-points generation uses user_config."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    _create_and_enable_config(client, headers)

    with patch(
        "app.agents.llm._real_response",
        return_value=_outline_response(),
    ) as mock_real:
        resp = client.post(
            f"/api/v1/courses/{course_id}/knowledge-points/generate",
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    mock_real.assert_called_once()
    user_config = _extract_user_config(mock_real.call_args)
    assert user_config is not None
    assert user_config["base_url"] == LLM_CONFIG_PAYLOAD["base_url"]
    assert user_config["model"] == LLM_CONFIG_PAYLOAD["model"]


# ---------------------------------------------------------------------------
# quizzes: uses user_config when an active config exists
# ---------------------------------------------------------------------------


def test_quizzes_uses_user_config(
    client, tmp_path, monkeypatch
) -> None:
    """With active config, quiz generation uses user_config."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    # Generate knowledge points first (mock mode, no config yet) so the
    # quiz agent has KPs to bind questions to.
    kp_resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert kp_resp.status_code == 200, kp_resp.text
    _create_and_enable_config(client, headers)

    with patch(
        "app.agents.llm._real_response",
        return_value=_quiz_response(),
    ) as mock_real:
        resp = client.post(
            "/api/v1/quizzes",
            json={"course_id": course_id},
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    mock_real.assert_called_once()
    user_config = _extract_user_config(mock_real.call_args)
    assert user_config is not None
    assert user_config["base_url"] == LLM_CONFIG_PAYLOAD["base_url"]
    assert user_config["model"] == LLM_CONFIG_PAYLOAD["model"]
