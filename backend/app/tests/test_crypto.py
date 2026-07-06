"""Tests for the API key encryption utilities (``app.core.crypto``).

These tests pin down the contract of the Fernet-based encryption helpers
used to store user-provided LLM API keys at rest: encrypt/decrypt must be
inverse operations, ciphertext must not leak the plaintext, and a wrong
key must fail loudly. ``mask_api_key`` is also covered so logs can show a
redacted form of a key without exposing it.
"""
import pytest

from app.core.crypto import decrypt, encrypt, mask_api_key


def test_encrypt_decrypt_roundtrip() -> None:
    """decrypt(encrypt(plain)) must return the original plaintext."""
    plaintext = "sk-abcdef1234567890"
    ciphertext = encrypt(plaintext)
    assert decrypt(ciphertext) == plaintext


def test_ciphertext_not_equal_plaintext() -> None:
    """The ciphertext must differ from the plaintext."""
    plaintext = "sk-abcdef1234567890"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext


def test_ciphertext_does_not_contain_plaintext() -> None:
    """The ciphertext must not contain the plaintext as a substring."""
    plaintext = "sk-abcdef1234567890"
    ciphertext = encrypt(plaintext)
    assert plaintext not in ciphertext


def test_decrypt_wrong_key_raises(monkeypatch) -> None:
    """Decrypting with a different key must raise an exception."""
    from app.core.config import settings

    plaintext = "sk-abcdef1234567890"
    ciphertext = encrypt(plaintext)

    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "a-totally-different-key")
    with pytest.raises(Exception):
        decrypt(ciphertext)


def test_encrypt_empty_string() -> None:
    """Empty strings must round-trip through encrypt/decrypt."""
    ciphertext = encrypt("")
    assert decrypt(ciphertext) == ""


def test_mask_api_key() -> None:
    """mask_api_key keeps the first 3 and last 4 chars, starring the middle."""
    result = mask_api_key("sk-abcdef123456")
    assert result.startswith("sk-")
    assert result.endswith("3456")
    assert "*" in result
    # The sensitive middle portion must not appear in the masked output.
    assert "abcdef" not in result


def test_mask_api_key_short_input() -> None:
    """Inputs of length <= 7 are fully masked with stars."""
    result = mask_api_key("short12")
    assert result == "*" * 7
    assert "short12" not in result
