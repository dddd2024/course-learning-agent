"""UserLLMConfig ORM model.

A ``UserLLMConfig`` stores a per-user, OpenAI-compatible LLM provider
configuration. The ``api_key`` is encrypted at rest via the helpers in
``app.core.crypto`` and is never exposed in plaintext; the
``api_key_masked`` property returns a redacted form suitable for logs
and API responses.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.models.base import Base, TimestampMixin


class UserLLMConfig(Base, TimestampMixin):
    """A user-scoped LLM provider configuration."""

    __tablename__ = "user_llm_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    provider = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    base_url = Column(String(255), nullable=False)
    model = Column(String(100), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    temperature = Column(Float, default=0.2, nullable=False)
    max_tokens = Column(Integer, default=2000, nullable=False)
    timeout_seconds = Column(Integer, default=60, nullable=False)
    last_test_status = Column(
        String(20), default="untested", nullable=False
    )
    last_test_error = Column(Text)
    last_test_at = Column(DateTime)

    @property
    def api_key_masked(self) -> str:
        """Return a redacted form of the stored API key.

        Decrypts ``api_key_encrypted`` on the fly and applies
        :func:`app.core.crypto.mask_api_key`. Any decryption failure is
        swallowed and a generic ``"***"`` placeholder is returned so the
        masked value can still be surfaced without leaking secrets.
        """
        from app.core.crypto import decrypt, mask_api_key

        try:
            return mask_api_key(decrypt(self.api_key_encrypted))
        except Exception:
            return "***"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<UserLLMConfig id={self.id} user_id={self.user_id} "
            f"provider={self.provider!r} name={self.name!r}>"
        )
