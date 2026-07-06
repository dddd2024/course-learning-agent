"""Service layer for user-scoped LLM provider configs.

All queries are scoped by ``user_id`` so a config owned by another user
is invisible to callers. The plaintext API key never enters persistence:
:func:`create_config` / :func:`update_config` encrypt it via
:func:`app.core.crypto.encrypt` before flushing, and responses only ever
surface the masked form via the ``UserLLMConfig.api_key_masked`` property.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.llm import _real_response
from app.core.crypto import decrypt, encrypt
from app.models.llm_config import UserLLMConfig


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

    Builds the ``user_config`` dict expected by
    :func:`app.agents.llm._real_response` from the stored (encrypted) API
    key and the provider settings, then invokes the real path. Any
    exception is swallowed and surfaced as ``status="failed"`` with the
    error message so the caller can persist ``last_test_error``.

    Returns
    -------
    dict
        ``{"status": "success" | "failed", "error": str | None,
        "provider": str, "model": str}``.
    """
    user_config = {
        "base_url": config.base_url,
        "model": config.model,
        "api_key": decrypt(config.api_key_encrypted),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout_seconds": config.timeout_seconds,
    }
    try:
        _real_response("test", "course_qa", None, user_config)
        return {
            "status": "success",
            "error": None,
            "provider": config.provider,
            "model": config.model,
        }
    except Exception as exc:  # noqa: BLE001 - surface any failure to caller
        return {
            "status": "failed",
            "error": str(exc)[:500],
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
