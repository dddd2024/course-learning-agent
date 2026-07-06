"""Symmetric encryption helpers for user-provided LLM API keys.

API keys must be encrypted at rest. We use Fernet (AES-128-CBC + HMAC
SHA256) from the ``cryptography`` package. The key is derived from
``settings.LLM_CONFIG_SECRET_KEY``: if the configured value is already a
valid urlsafe-base64 32-byte string it is used directly, otherwise a
deterministic key is derived via SHA-256 so users can supply any string.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet() -> Fernet:
    """Build a Fernet instance from ``settings.LLM_CONFIG_SECRET_KEY``.

    If the configured secret is a valid Fernet key (urlsafe base64 of 32
    bytes) it is used as-is. Otherwise a 32-byte key is derived by
    hashing the secret with SHA-256 and re-encoding as urlsafe base64.
    """
    raw = settings.LLM_CONFIG_SECRET_KEY.encode()
    try:
        return Fernet(raw)
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` and return a base64 ciphertext string."""
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a ``ciphertext`` produced by :func:`encrypt`.

    Raises :class:`cryptography.fernet.InvalidToken` if the ciphertext is
    tampered with or was produced under a different key.
    """
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise InvalidToken(f"failed to decrypt ciphertext: {exc}") from exc


def mask_api_key(api_key: str) -> str:
    """Return a redacted form of ``api_key`` for logs or UI display.

    Keeps the first 3 and last 4 characters and replaces the middle with
    stars. Inputs of length 7 or shorter are fully replaced with stars
    so no recognisable fragment leaks.
    """
    if len(api_key) <= 7:
        return "*" * len(api_key)
    return f"{api_key[:3]}***{api_key[-4:]}"
