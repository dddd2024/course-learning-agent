"""LLM API Key encryption-key rotation (security Task E).

When the ``LLM_CONFIG_SECRET_KEY`` needs to be rotated (e.g. suspected
leak), :func:`rotate_llm_config_secret` re-encrypts every stored
``api_key_encrypted`` from the old Fernet secret to a new one so no API
keys are lost. The companion CLI script is
``scripts/rotate_llm_config_secret.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import settings
from app.models.llm_config import UserLLMConfig


@dataclass
class RotationReport:
    """Outcome of a rotation run."""

    affected: int = 0  # configs considered for rotation
    reencrypted: int = 0  # configs successfully re-encrypted
    failed: int = 0  # configs that could not be decrypted with old secret
    applied: bool = False  # whether changes were written


def _fernet_with_secret(secret: str):
    """Build a Fernet instance for an arbitrary secret string.

    Mirrors :func:`app.core.crypto._get_fernet` but for an explicit
    secret (not the global ``settings`` value) so rotation can decrypt
    with the old key and encrypt with the new one.
    """
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    raw = secret.encode()
    try:
        return Fernet(raw)
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        return Fernet(derived)


def rotate_llm_config_secret(
    db: Session,
    *,
    old_secret: str,
    new_secret: str,
    apply: bool = False,
) -> RotationReport:
    """Re-encrypt all LLM API keys from ``old_secret`` to ``new_secret``.

    Steps:
    1. Load every ``UserLLMConfig`` row.
    2. Decrypt ``api_key_encrypted`` with a Fernet built from ``old_secret``.
    3. Re-encrypt the plaintext with a Fernet built from ``new_secret``.
    4. If ``apply`` is True, persist; otherwise just report counts.

    Configs whose ciphertext cannot be decrypted with ``old_secret`` are
    counted as ``failed`` and left untouched (so the operator can
    investigate before forcing a rotation).
    """
    old_fernet = _fernet_with_secret(old_secret)
    new_fernet = _fernet_with_secret(new_secret)

    configs = db.query(UserLLMConfig).all()
    report = RotationReport(affected=len(configs), applied=apply)

    if not apply:
        # Dry-run: count how many would succeed vs fail.
        for cfg in configs:
            try:
                old_fernet.decrypt(cfg.api_key_encrypted.encode()).decode()
                report.reencrypted += 1
            except Exception:
                report.failed += 1
        return report

    for cfg in configs:
        try:
            plaintext = old_fernet.decrypt(cfg.api_key_encrypted.encode()).decode()
            cfg.api_key_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
            report.reencrypted += 1
        except Exception:
            report.failed += 1

    db.commit()
    return report
