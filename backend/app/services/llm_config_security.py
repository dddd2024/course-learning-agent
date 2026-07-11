"""LLM API Key encryption-key rotation (security Task E).

When the ``LLM_CONFIG_SECRET_KEY`` needs to be rotated (e.g. suspected
leak), :func:`rotate_llm_config_secret` re-encrypts every stored
``api_key_encrypted`` from the old Fernet secret to a new one so no API
keys are lost. The companion CLI script is
``scripts/rotate_llm_config_secret.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import settings
from app.models.llm_config import UserLLMConfig


def validate_llm_base_url(value: str) -> str:
    """Reject malformed and production-private LLM endpoints.

    Development keeps local endpoints available for the existing Windows
    workflow. Production resolves DNS before accepting a URL so a hostname
    cannot bypass the private-address policy.
    """
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL 必须是包含主机名的 http 或 https 地址")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不允许包含用户名或密码")
    if settings.ENVIRONMENT.lower() != "production":
        return value.rstrip("/")

    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("生产环境不允许 LLM Base URL 指向本地地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except OSError as exc:
        raise ValueError("Base URL 主机名无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
            raise ValueError("生产环境不允许 LLM Base URL 指向私有或保留地址")
        if str(ip) == "169.254.169.254":
            raise ValueError("生产环境不允许 LLM Base URL 指向云元数据地址")
    return value.rstrip("/")


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
