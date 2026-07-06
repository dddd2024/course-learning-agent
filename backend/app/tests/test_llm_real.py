"""Tests for the real OpenAI-compatible LLM call layer (Task 4).

Strict TDD: these tests are written first and fail until ``_real_response``
and the three-layer fallback in ``call_llm`` are implemented.

The httpx client is mocked so the tests run offline and fast. They pin
down the contract of the real provider path:

- ``_real_response`` parses ``choices[0].message.content`` as a JSON dict.
- The request body carries ``response_format={"type": "json_object"}``.
- On a 400 the call retries once without ``response_format``.
- On a 500 the call raises (no internal fallback).
- ``call_llm`` routes through ``_real_response`` when a ``user_config``
  is supplied, and falls back to the mock provider on real-path failure.
- Without a ``user_config``, the system ``LLM_PROVIDER`` setting decides.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.llm import _real_response, call_llm
from app.core.config import settings


USER_CONFIG = {
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key": "sk-test-key",
    "temperature": 0.1,
    "max_tokens": 500,
    "timeout_seconds": 30,
}


def _ok_response(content: str) -> MagicMock:
    """Build a fake httpx.Response with status 200 and the given content."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _err_response(status_code: int) -> MagicMock:
    """Build a fake httpx.Response with the given error status code."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock(
        side_effect=RuntimeError(f"HTTP {status_code}")
    )
    return resp


def _client_from_patch(mock_client_cls: MagicMock) -> MagicMock:
    """Return the mock client yielded by ``with httpx.Client(...) as client``."""
    return mock_client_cls.return_value.__enter__.return_value


# ---------------------------------------------------------------------------
# SubTask 4.2: _real_response behaviour
# ---------------------------------------------------------------------------


def test_real_response_success() -> None:
    """_real_response parses choices[0].message.content as a JSON dict."""
    payload = {
        "answer": "梯度下降是迭代优化算法",
        "key_points": [],
        "citations": [],
        "not_found": False,
        "follow_up_questions": [],
    }
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _client_from_patch(mock_client_cls)
        mock_client.post.return_value = _ok_response(json.dumps(payload))

        result = _real_response("prompt", "course_qa", None, USER_CONFIG)

    assert isinstance(result, dict)
    assert result == payload
    mock_client.post.assert_called_once()


def test_real_response_with_response_format() -> None:
    """The request body includes response_format={type: json_object}."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _client_from_patch(mock_client_cls)
        mock_client.post.return_value = _ok_response(
            json.dumps({"answer": "x"})
        )

        _real_response("prompt", "course_qa", None, USER_CONFIG)

    assert mock_client.post.call_count == 1
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["response_format"] == {"type": "json_object"}


def test_real_response_400_fallback_no_response_format() -> None:
    """On a 400, the call retries once without response_format in the body."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _client_from_patch(mock_client_cls)
        mock_client.post.side_effect = [
            _err_response(400),
            _ok_response(json.dumps({"answer": "x"})),
        ]

        result = _real_response("prompt", "course_qa", None, USER_CONFIG)

    assert result == {"answer": "x"}
    assert mock_client.post.call_count == 2
    # The retry must NOT carry response_format. (The first attempt's
    # body is mutated in place by body.pop, so we cannot inspect it
    # after the fact; the "sends response_format" contract is covered
    # by test_real_response_with_response_format above.)
    _, retry_kwargs = mock_client.post.call_args_list[1]
    assert "response_format" not in retry_kwargs["json"]


def test_real_response_500_raises() -> None:
    """On a 500, _real_response raises (no internal fallback)."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _client_from_patch(mock_client_cls)
        mock_client.post.return_value = _err_response(500)

        with pytest.raises(Exception):
            _real_response("prompt", "course_qa", None, USER_CONFIG)

    # No retry on 500: exactly one call.
    assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# SubTask 4.3: call_llm three-layer fallback
# ---------------------------------------------------------------------------


def test_call_llm_with_user_config() -> None:
    """call_llm with user_config routes to _real_response with that config."""
    with patch("app.agents.llm._real_response") as mock_real:
        mock_real.return_value = {"answer": "from real"}

        result = call_llm("prompt", "course_qa", user_config=USER_CONFIG)

    mock_real.assert_called_once_with(
        "prompt", "course_qa", None, USER_CONFIG
    )
    assert result == {"answer": "from real"}


def test_call_llm_fallback_to_mock_on_real_failure() -> None:
    """If _real_response raises, call_llm falls back to the mock payload."""
    with patch(
        "app.agents.llm._real_response",
        side_effect=RuntimeError("boom"),
    ):
        result = call_llm("prompt", "course_qa", user_config=USER_CONFIG)

    # Mock provider returns structured JSON for course_qa.
    assert isinstance(result, dict)
    assert "answer" in result
    assert "key_points" in result
    assert "citations" in result
    assert "not_found" in result
    assert "follow_up_questions" in result


def test_call_llm_no_user_config_mock_provider(monkeypatch) -> None:
    """Without user_config and LLM_PROVIDER=mock, returns the mock payload."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    result = call_llm("prompt", "course_qa")

    assert isinstance(result, dict)
    assert "answer" in result


def test_call_llm_no_user_config_real_provider(monkeypatch) -> None:
    """Without user_config and LLM_PROVIDER=real, calls the real httpx path."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "real")
    payload = {
        "answer": "real answer",
        "key_points": [],
        "citations": [],
        "not_found": False,
        "follow_up_questions": [],
    }
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _client_from_patch(mock_client_cls)
        mock_client.post.return_value = _ok_response(json.dumps(payload))

        result = call_llm("prompt", "course_qa")

    assert result == payload
    mock_client.post.assert_called_once()
