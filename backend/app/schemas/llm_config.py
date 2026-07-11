"""Pydantic schemas for the user LLM config endpoints.

``LLMConfigCreate`` / ``LLMConfigUpdate`` accept the API key in
plaintext (the service layer encrypts it before persistence).
``LLMConfigResponse`` is built from the ORM via ``from_attributes`` and
exposes only the masked form of the key: ``api_key_encrypted`` and the
plaintext key are never serialised.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic import field_validator
from urllib.parse import urlsplit


def _validate_url_shape(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL 必须是包含主机名的 http 或 https 地址")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不允许包含用户名或密码")
    return value.rstrip("/")


class LLMConfigCreate(BaseModel):
    """Payload for creating a user LLM config.

    ``api_key`` is the plaintext key supplied by the user; it is
    encrypted by the service layer before being stored as
    ``api_key_encrypted``.
    """

    provider: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    base_url: str = Field(..., min_length=1, max_length=255)
    model: str = Field(..., min_length=1, max_length=100)
    api_key: str = Field(..., min_length=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=16000)
    timeout_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return _validate_url_shape(value)


class LLMConfigUpdate(BaseModel):
    """Payload for patching a user LLM config (all fields optional)."""

    provider: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    base_url: Optional[str] = Field(
        default=None, min_length=1, max_length=255
    )
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    api_key: Optional[str] = Field(default=None, min_length=1)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=16000)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=300)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        return _validate_url_shape(value) if value is not None else value


class LLMConfigResponse(BaseModel):
    """A user LLM config returned to the client.

    The masked API key is read from the ORM ``api_key_masked`` property.
    ``api_key_encrypted`` and the plaintext key are intentionally not
    declared here so they can never leak through serialisation.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    name: str
    base_url: str
    model: str
    api_key_masked: str
    enabled: bool
    is_default: bool
    temperature: float
    max_tokens: int
    timeout_seconds: int
    last_test_status: str
    last_test_error: Optional[str] = None
    last_test_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class LLMConfigListResponse(BaseModel):
    """List of LLM configs for the current user."""

    items: List[LLMConfigResponse]


class LLMConfigTestResponse(BaseModel):
    """Result of testing an LLM config connectivity."""

    status: str  # "success" / "failed"
    error: Optional[str] = None
    provider: str
    model: str


class LLMConfigActiveResponse(BaseModel):
    """The active (default + enabled) LLM config, if any."""

    config: Optional[LLMConfigResponse] = None
