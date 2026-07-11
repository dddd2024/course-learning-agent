"""Service layer for user-scoped LLM provider configs.

All queries are scoped by ``user_id`` so a config owned by another user
is invisible to callers. The plaintext API key never enters persistence:
:func:`create_config` / :func:`update_config` encrypt it via
:func:`app.core.crypto.encrypt` before flushing, and responses only ever
surface the masked form via the ``UserLLMConfig.api_key_masked`` property.
"""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.models.llm_config import UserLLMConfig
from app.services.llm_config_security import validate_llm_base_url


def get_user_configs(db: Session, user_id: int) -> list[UserLLMConfig]:
    """Return all LLM configs owned by ``user_id``."""
    return (
        db.query(UserLLMConfig)
        .filter(UserLLMConfig.user_id == user_id)
        .order_by(UserLLMConfig.id.asc())
        .all()
    )


def get_config(
    db: Session, config_id: int, user_id: int
) -> UserLLMConfig | None:
    """Return the config if it belongs to ``user_id``, else None."""
    return (
        db.query(UserLLMConfig)
        .filter(
            UserLLMConfig.id == config_id,
            UserLLMConfig.user_id == user_id,
        )
        .first()
    )


def get_active_config(db: Session, user_id: int) -> UserLLMConfig | None:
    """Return the user's default config (``is_default=True``), if any."""
    return (
        db.query(UserLLMConfig)
        .filter(
            UserLLMConfig.user_id == user_id,
            UserLLMConfig.is_default == True,  # noqa: E712 - SQLAlchemy
        )
        .first()
    )


def build_user_config(config: UserLLMConfig) -> dict:
    """Convert a ``UserLLMConfig`` ORM row into the dict ``call_llm`` expects.

    Decrypts the stored API key and assembles the ``base_url`` /
    ``model`` / ``api_key`` / ``temperature`` / ``max_tokens`` /
    ``timeout_seconds`` fields consumed by
    :func:`app.agents.llm._real_response`.
    """
    return {
        "base_url": config.base_url,
        "model": config.model,
        "api_key": decrypt(config.api_key_encrypted),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout_seconds": config.timeout_seconds,
    }


def create_config(db: Session, user_id: int, data: dict) -> UserLLMConfig:
    """Create a config, encrypting the plaintext ``api_key`` before persist."""
    data = dict(data)
    data["base_url"] = validate_llm_base_url(data["base_url"])
    config = UserLLMConfig(
        user_id=user_id,
        provider=data["provider"],
        name=data["name"],
        base_url=data["base_url"],
        model=data["model"],
        api_key_encrypted=encrypt(data["api_key"]),
        temperature=data.get("temperature", 0.2),
        max_tokens=data.get("max_tokens", 2000),
        timeout_seconds=data.get("timeout_seconds", 60),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_config(
    db: Session, config: UserLLMConfig, data: dict
) -> UserLLMConfig:
    """Patch a config in place. Re-encrypts ``api_key`` when supplied."""
    data = dict(data)
    if data.get("base_url") is not None:
        data["base_url"] = validate_llm_base_url(data["base_url"])
    for field in [
        "provider",
        "name",
        "base_url",
        "model",
        "temperature",
        "max_tokens",
        "timeout_seconds",
    ]:
        if field in data and data[field] is not None:
            setattr(config, field, data[field])
    if "api_key" in data and data["api_key"]:
        config.api_key_encrypted = encrypt(data["api_key"])
    db.commit()
    db.refresh(config)
    return config


def delete_config(db: Session, config: UserLLMConfig) -> None:
    """Remove a config from the database."""
    db.delete(config)
    db.commit()


def enable_config(db: Session, config: UserLLMConfig) -> UserLLMConfig:
    """Mark ``config`` as the user's default, disabling the others.

    Sets ``is_default=False`` on every other config owned by the same
    user (mutual exclusivity) and flips ``enabled=True`` on the target.
    """
    db.query(UserLLMConfig).filter(
        UserLLMConfig.user_id == config.user_id,
        UserLLMConfig.id != config.id,
    ).update({UserLLMConfig.is_default: False})
    config.is_default = True
    config.enabled = True
    db.commit()
    db.refresh(config)
    return config


def test_connection(config: UserLLMConfig) -> dict:
    """Probe the provider without mutating ``enabled`` state.

    This performs a **low-level HTTP probe** against
    ``{base_url}/chat/completions`` rather than reusing the Agent-facing
    :func:`app.agents.llm._real_response` path. The probe only verifies
    that the service is reachable, the API key authenticates, the model
    name is accepted, and the response is an OpenAI Chat Completions
    envelope. It does **not** require the model's reply body to be JSON
    — a plain-text ``"OK"`` reply is enough to pass.

    Success criteria: HTTP 2xx + ``resp.json()`` succeeds +
    ``choices[0].message.content`` exists.

    Returns
    -------
    dict
        ``{"status": "success" | "failed", "error": str | None,
        "provider": str, "model": str}``.
    """
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {decrypt(config.api_key_encrypted)}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": "请回复 OK。"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    try:
        with httpx.Client(timeout=config.timeout_seconds, follow_redirects=False) as client:
            resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        snippet = (exc.response.text or "")[:300]
        return _failed(config, f"HTTP {exc.response.status_code}: {snippet}")
    except httpx.HTTPError as exc:
        # Connection / timeout / DNS errors.
        return _failed(config, f"网络请求失败：{exc}")

    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 - any JSON parse failure
        snippet = (resp.text or "")[:300]
        return _failed(
            config,
            f"LLM 服务返回的不是 JSON，可能 Base URL 指向网页/鉴权页/错误页。响应片段: {snippet}",
        )

    try:
        _ = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        snippet = str(data)[:300]
        return _failed(
            config,
            f"LLM 响应不是 OpenAI Chat Completions 格式（缺少 choices）。响应片段: {snippet}",
        )

    return {
        "status": "success",
        "error": None,
        "provider": config.provider,
        "model": config.model,
    }


def _failed(config: UserLLMConfig, error: str) -> dict:
    return {
        "status": "failed",
        "error": error[:500],
        "provider": config.provider,
        "model": config.model,
    }


__all__ = [
    "get_user_configs",
    "get_config",
    "get_active_config",
    "build_user_config",
    "create_config",
    "update_config",
    "delete_config",
    "enable_config",
    "test_connection",
]
