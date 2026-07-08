"""Tests for the LLM config service layer.

Covers:
- create_config encrypts the API key before persistence
- get_active_config returns the default config (or None)
- enable_config enforces per-user exclusivity
- test_connection probes /chat/completions via low-level HTTP and does
  NOT require the model body to be JSON (only connection/auth/format)
- get_user_configs filters by user_id
"""
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.crypto import decrypt
from app.models.base import Base
from app.models.user import User
from app.services.llm_config_service import (
    create_config,
    enable_config,
    get_active_config,
    get_user_configs,
)
from app.services.llm_config_service import (
    test_connection as run_test_connection,
)

PLAINTEXT_KEY = "sk-abcdef1234567890"


def _fresh_session() -> Session:
    """Return a fresh in-memory SQLite session with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _create_user(db: Session, username: str = "alice") -> User:
    """Create and return a user row for the test DB."""
    user = User(
        username=username,
        password_hash="x",
        email=f"{username}@example.com",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _config_payload(name: str = "my-openai") -> dict:
    """Return a create_config payload dict."""
    return {
        "provider": "openai",
        "name": name,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": PLAINTEXT_KEY,
        "temperature": 0.2,
        "max_tokens": 2000,
        "timeout_seconds": 60,
    }


# ---------------------------------------------------------------------------
# create_config
# ---------------------------------------------------------------------------


def test_create_config_encrypts_api_key() -> None:
    """create_config stores an encrypted api_key, never the plaintext."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        config = create_config(db, user.id, _config_payload())

        assert config.id is not None
        assert config.user_id == user.id
        # The stored ciphertext must not equal the plaintext.
        assert config.api_key_encrypted != PLAINTEXT_KEY
        # The plaintext must not appear anywhere in the ciphertext.
        assert PLAINTEXT_KEY not in config.api_key_encrypted
        # Decrypting must recover the original key.
        assert decrypt(config.api_key_encrypted) == PLAINTEXT_KEY
    finally:
        db.close()


# ---------------------------------------------------------------------------
# get_active_config
# ---------------------------------------------------------------------------


def test_get_active_config_returns_default() -> None:
    """get_active_config returns the user's is_default=True config."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        cfg_a = create_config(db, user.id, _config_payload(name="a"))
        cfg_b = create_config(db, user.id, _config_payload(name="b"))
        cfg_b.is_default = True
        db.commit()

        active = get_active_config(db, user.id)
        assert active is not None
        assert active.id == cfg_b.id
        assert active.is_default is True
    finally:
        db.close()


def test_get_active_config_returns_none() -> None:
    """get_active_config returns None when no config exists for the user."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        assert get_active_config(db, user.id) is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# enable_config
# ---------------------------------------------------------------------------


def test_enable_config_exclusivity() -> None:
    """enable_config sets is_default=True only on the target config."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        cfg_a = create_config(db, user.id, _config_payload(name="a"))
        cfg_b = create_config(db, user.id, _config_payload(name="b"))

        # Pre-enable cfg_a so we can verify it gets toggled off.
        cfg_a.is_default = True
        cfg_a.enabled = True
        db.commit()

        enabled = enable_config(db, cfg_b)

        assert enabled.is_default is True
        assert enabled.enabled is True

        db.refresh(cfg_a)
        assert cfg_a.is_default is False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# test_connection (low-level HTTP probe; does NOT require JSON body)
# ---------------------------------------------------------------------------

def _client_from_patch(mock_client_cls):
    """Return the mock client yielded by ``with httpx.Client(...) as client``."""
    return mock_client_cls.return_value.__enter__.return_value


def _probe_ok(content: str = "OK") -> httpx.Response:
    """Build a real 2xx httpx.Response whose body is OpenAI Chat Completions."""
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request("POST", "https://example/v1/chat/completions"),
    )


def _probe_http_error(status_code: int, body: str = "nope") -> httpx.Response:
    """Build a real httpx.Response with an error status code."""
    return httpx.Response(
        status_code,
        text=body,
        request=httpx.Request("POST", "https://example/v1/chat/completions"),
    )


def test_llm_config_connection_success_with_plain_text_content() -> None:
    """test_connection succeeds when the model replies plain text (not JSON).

    The probe only checks 2xx + JSON body + choices[0].message.content; it
    must NOT parse ``content`` itself, so a normal ``OK`` reply is enough.
    """
    db = _fresh_session()
    try:
        user = _create_user(db)
        config = create_config(db, user.id, _config_payload())

        with patch("httpx.Client") as mock_client_cls:
            mock_client = _client_from_patch(mock_client_cls)
            mock_client.post.return_value = _probe_ok("OK")

            result = run_test_connection(config)

        assert result["status"] == "success"
        assert result["error"] is None
        assert result["provider"] == config.provider
        assert result["model"] == config.model
        mock_client.post.assert_called_once()
        # The probe body must NOT carry response_format.
        _, kwargs = mock_client.post.call_args
        assert "response_format" not in kwargs["json"]
        # The probe sends a tiny prompt, temperature=0, max_tokens=16.
        body = kwargs["json"]
        assert body["temperature"] == 0
        assert body["max_tokens"] == 16
    finally:
        db.close()


@pytest.mark.parametrize("status_code", [401, 403, 404, 429])
def test_llm_config_connection_reports_http_error(status_code: int) -> None:
    """test_connection reports HTTP errors with the status code + snippet."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        config = create_config(db, user.id, _config_payload())

        with patch("httpx.Client") as mock_client_cls:
            mock_client = _client_from_patch(mock_client_cls)
            mock_client.post.return_value = _probe_http_error(
                status_code, "forbidden"
            )

            result = run_test_connection(config)

        assert result["status"] == "failed"
        assert result["error"] is not None
        assert str(status_code) in result["error"]
        assert result["provider"] == config.provider
        assert result["model"] == config.model
    finally:
        db.close()


def test_llm_config_connection_reports_non_json_response() -> None:
    """test_connection reports 'non-JSON response' when resp.json() raises."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        config = create_config(db, user.id, _config_payload())

        resp = httpx.Response(
            200,
            text="<html>login page</html>",
            request=httpx.Request("POST", "https://example/v1/chat/completions"),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = _client_from_patch(mock_client_cls)
            mock_client.post.return_value = resp

            result = run_test_connection(config)

        assert result["status"] == "failed"
        assert result["error"] is not None
        # The message must explain the body is not JSON (not raw Expecting value).
        assert "JSON" in result["error"] or "json" in result["error"]
        assert "Expecting value" not in result["error"]
    finally:
        db.close()


def test_llm_config_connection_reports_missing_choices() -> None:
    """test_connection reports 'not OpenAI format' when choices is absent."""
    db = _fresh_session()
    try:
        user = _create_user(db)
        config = create_config(db, user.id, _config_payload())

        resp = httpx.Response(
            200,
            json={"some_other_field": 1},
            request=httpx.Request("POST", "https://example/v1/chat/completions"),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = _client_from_patch(mock_client_cls)
            mock_client.post.return_value = resp

            result = run_test_connection(config)

        assert result["status"] == "failed"
        assert result["error"] is not None
        assert "OpenAI" in result["error"] or "choices" in result["error"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# get_user_configs
# ---------------------------------------------------------------------------


def test_get_user_configs_filters_by_user() -> None:
    """get_user_configs only returns configs owned by the given user."""
    db = _fresh_session()
    try:
        alice = _create_user(db, username="alice")
        bob = _create_user(db, username="bob")

        create_config(db, alice.id, _config_payload(name="alice-a"))
        create_config(db, alice.id, _config_payload(name="alice-b"))
        create_config(db, bob.id, _config_payload(name="bob-a"))

        alice_configs = get_user_configs(db, alice.id)
        bob_configs = get_user_configs(db, bob.id)

        assert len(alice_configs) == 2
        assert len(bob_configs) == 1
        for cfg in alice_configs:
            assert cfg.user_id == alice.id
        for cfg in bob_configs:
            assert cfg.user_id == bob.id
    finally:
        db.close()
