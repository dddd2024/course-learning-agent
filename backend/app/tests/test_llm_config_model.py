"""Tests for the UserLLMConfig model and LLM config schemas (Task 2).

Strict TDD: these tests are written first and fail until the
``UserLLMConfig`` model and the ``llm_config`` schemas are implemented.

Covers:
- UserLLMConfig instance creation and default values
- api_key_masked property hides the plaintext API key
- user_llm_configs table is created by Base.metadata
- LLMConfigResponse does not leak api_key_encrypted or plaintext
"""
from datetime import datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.crypto import decrypt, encrypt, mask_api_key
from app.models.base import Base
from app.models.llm_config import UserLLMConfig
from app.schemas.llm_config import LLMConfigResponse

PLAINTEXT_KEY = "sk-abcdef1234567890"


def _fresh_engine():
    """Return a brand-new in-memory SQLite engine for table/flush tests."""
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


# ---------------------------------------------------------------------------
# SubTask 2.4: model creation + defaults
# ---------------------------------------------------------------------------


def test_create_llm_config() -> None:
    """A UserLLMConfig instance persists with the expected defaults."""
    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    cfg = UserLLMConfig(
        user_id=1,
        provider="openai",
        name="my-openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key_encrypted=encrypt(PLAINTEXT_KEY),
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)

    assert cfg.id is not None
    assert cfg.user_id == 1
    assert cfg.provider == "openai"
    assert cfg.name == "my-openai"
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.model == "gpt-4o-mini"
    # The stored ciphertext must not equal the plaintext.
    assert cfg.api_key_encrypted != PLAINTEXT_KEY
    # Defaults applied on flush.
    assert cfg.enabled is False
    assert cfg.is_default is False
    assert cfg.temperature == 0.2
    assert cfg.max_tokens == 2000
    assert cfg.timeout_seconds == 60
    assert cfg.last_test_status == "untested"
    assert cfg.last_test_error is None
    assert cfg.last_test_at is None
    assert cfg.created_at is not None
    db.close()


# ---------------------------------------------------------------------------
# SubTask 2.4: api_key_masked property
# ---------------------------------------------------------------------------


def test_api_key_masked_property() -> None:
    """api_key_masked returns the redacted form, never the plaintext."""
    cfg = UserLLMConfig(
        user_id=1,
        provider="openai",
        name="my-openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key_encrypted=encrypt(PLAINTEXT_KEY),
    )
    masked = cfg.api_key_masked
    expected = mask_api_key(PLAINTEXT_KEY)
    assert masked == expected
    # Plaintext must never appear in the masked output.
    assert PLAINTEXT_KEY not in masked
    # The masked form keeps the head/tail prefix/suffix.
    assert masked.startswith("sk-")
    assert masked.endswith("7890")

    # Decrypting the stored ciphertext must still recover the plaintext,
    # i.e. the property did not mutate the stored value.
    assert decrypt(cfg.api_key_encrypted) == PLAINTEXT_KEY


# ---------------------------------------------------------------------------
# SubTask 2.4: table creation
# ---------------------------------------------------------------------------


def test_table_created() -> None:
    """Base.metadata.create_all creates the user_llm_configs table."""
    # Importing the models package registers the table on Base.metadata.
    import app.models  # noqa: F401

    assert "user_llm_configs" in Base.metadata.tables

    engine = _fresh_engine()
    Base.metadata.create_all(bind=engine)
    table_names = inspect(engine).get_table_names()
    assert "user_llm_configs" in table_names


# ---------------------------------------------------------------------------
# SubTask 2.4: response schema does not leak secrets
# ---------------------------------------------------------------------------


def test_schema_response_no_plaintext() -> None:
    """LLMConfigResponse hides api_key_encrypted and plaintext api_key."""
    cfg = UserLLMConfig(
        id=1,
        user_id=1,
        provider="openai",
        name="my-openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key_encrypted=encrypt(PLAINTEXT_KEY),
        enabled=False,
        is_default=False,
        temperature=0.2,
        max_tokens=2000,
        timeout_seconds=60,
        last_test_status="untested",
        last_test_error=None,
        last_test_at=None,
        created_at=datetime(2026, 7, 6, 12, 0, 0),
    )

    response = LLMConfigResponse.model_validate(cfg)
    data = response.model_dump()

    # The encrypted ciphertext must never be exposed.
    assert "api_key_encrypted" not in data
    # Neither the plaintext nor the ciphertext may appear anywhere in
    # the serialised output.
    serialised = str(data)
    assert PLAINTEXT_KEY not in serialised
    assert cfg.api_key_encrypted not in serialised
    # The masked form must be present and correct.
    assert "api_key_masked" in data
    assert data["api_key_masked"] == mask_api_key(PLAINTEXT_KEY)
    # A handful of core fields are surfaced.
    assert data["id"] == 1
    assert data["user_id"] == 1
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
