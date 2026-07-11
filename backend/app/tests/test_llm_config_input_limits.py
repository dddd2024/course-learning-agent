"""Regression coverage for LLM endpoint safety and request limits."""

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.schemas.llm_config import LLMConfigCreate
from app.services.llm_config_security import validate_llm_base_url


def test_chat_question_has_a_finite_limit() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(course_id=1, conversation_id=1, question="x" * 4001)


def test_llm_resource_settings_have_finite_limits() -> None:
    base = {
        "provider": "custom", "name": "test", "base_url": "https://example.com/v1",
        "model": "example", "api_key": "not-a-real-key",
    }
    with pytest.raises(ValidationError):
        LLMConfigCreate(**base, max_tokens=16001)
    with pytest.raises(ValidationError):
        LLMConfigCreate(**base, timeout_seconds=301)


def test_production_rejects_private_llm_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="本地地址"):
        validate_llm_base_url("http://localhost:8000/v1")


def test_production_rechecks_dns_addresses(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        "app.services.llm_config_security.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="私有或保留"):
        validate_llm_base_url("https://example.invalid/v1")
