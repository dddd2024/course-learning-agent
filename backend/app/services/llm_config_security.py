"""LLM API Key encryption-key rotation (security Task E) + SSRF protection.

When the ``LLM_CONFIG_SECRET_KEY`` needs to be rotated (e.g. suspected
leak), :func:`rotate_llm_config_secret` re-encrypts every stored
``api_key_encrypted`` from the old Fernet secret to a new one so no API
keys are lost. The companion CLI script is
``scripts/rotate_llm_config_secret.py``.

SEC-V3-01: SSRF protection now applies in ALL environments (not just
production). Private/localhost endpoints are rejected unless
``settings.ALLOW_PRIVATE_LLM_ENDPOINTS`` is True. A new
:func:`validate_llm_base_url_request_time` function re-resolves DNS
before every actual HTTP request to prevent DNS rebinding attacks.
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


# --------------------------------------------------------------------------
# Shared IP-checking helpers
# --------------------------------------------------------------------------

def _is_cloud_metadata(ip: ipaddress._BaseAddress) -> bool:
    """Return True for the cloud metadata endpoint 169.254.169.254."""
    return str(ip) == "169.254.169.254"


def _check_ip_address(ip: ipaddress._BaseAddress, allow_private: bool) -> None:
    """Raise ValueError if *ip* is blocked.

    When *allow_private* is True, private/loopback/link-local/reserved
    addresses are allowed — but the cloud metadata endpoint
    169.254.169.254 is **always** blocked.
    """
    if _is_cloud_metadata(ip):
        raise ValueError(
            "LLM Base URL 不允许指向云元数据地址 (metadata/169.254.169.254)"
        )
    if allow_private:
        return
    if ip.is_loopback:
        raise ValueError(
            "LLM Base URL 不允许指向本地回环地址 (local/private/loopback)"
        )
    if ip.is_private:
        raise ValueError(
            "LLM Base URL 不允许指向私有地址 (private/reserved)"
        )
    if ip.is_link_local:
        raise ValueError(
            "LLM Base URL 不允许指向链路本地地址 (local/private/link-local)"
        )
    if ip.is_unspecified:
        raise ValueError(
            "LLM Base URL 不允许指向未指定地址 (reserved/private/unspecified)"
        )
    if ip.is_reserved:
        raise ValueError(
            "LLM Base URL 不允许指向保留地址 (reserved/private)"
        )


def _check_hostname_string(host: str, allow_private: bool) -> None:
    """Check a hostname that may be ``localhost`` or an IP literal."""
    if host == "localhost" or host.endswith(".localhost"):
        if not allow_private:
            raise ValueError(
                "LLM Base URL 不允许指向本地地址 (local/private/localhost)"
            )
        return

    # Try to parse as an IP address (IPv4 or IPv6).
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP — caller should do DNS resolution.
        return

    _check_ip_address(ip, allow_private)


# --------------------------------------------------------------------------
# Config-save-time validation
# --------------------------------------------------------------------------

def validate_llm_base_url(value: str) -> str:
    """Reject malformed and private LLM endpoints.

    SEC-V3-01: SSRF protection now applies in ALL environments, not just
    production. Private/localhost endpoints are rejected unless
    ``settings.ALLOW_PRIVATE_LLM_ENDPOINTS`` is True. DNS is resolved at
    save time so a hostname that points to a private IP is rejected.
    """
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL 必须是包含主机名的 http 或 https 地址")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不允许包含用户名或密码")

    host = parsed.hostname.lower()
    allow_private = settings.ALLOW_PRIVATE_LLM_ENDPOINTS

    # Check localhost / direct IP literals first (no DNS needed).
    _check_hostname_string(host, allow_private)

    # If the hostname was a direct IP, we're done.
    try:
        ipaddress.ip_address(host)
        return value.rstrip("/")
    except ValueError:
        pass  # Not an IP literal — proceed to DNS resolution.

    # DNS resolution: check every resolved address.
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)
        }
    except OSError as exc:
        raise ValueError("Base URL 主机名无法解析") from exc

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        _check_ip_address(ip, allow_private)

    return value.rstrip("/")


# --------------------------------------------------------------------------
# Request-time validation (DNS rebinding protection)
# --------------------------------------------------------------------------

def validate_llm_base_url_request_time(
    url_str: str,
) -> tuple[bool, str]:
    """Re-validate an LLM endpoint URL immediately before an HTTP request.

    Called before every actual HTTP request to an LLM endpoint. This
    prevents DNS rebinding: a URL that resolved to a public IP at
    config-save time might later resolve to a private IP.

    Returns ``(is_valid, reason)``. When *is_valid* is False, *reason*
    explains why the URL was rejected.
    """
    parsed = urlsplit(url_str.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return (False, "Base URL 格式无效")

    host = parsed.hostname.lower()
    allow_private = settings.ALLOW_PRIVATE_LLM_ENDPOINTS

    # Check localhost / direct IP literals (no DNS needed).
    if host == "localhost" or host.endswith(".localhost"):
        if not allow_private:
            return (
                False,
                f"LLM Base URL 指向本地地址 (local/private): {host}",
            )
        return (True, "OK")

    # If the hostname is a direct IP, validate it.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        try:
            _check_ip_address(ip, allow_private)
        except ValueError as exc:
            return (False, str(exc))
        return (True, "OK")

    # Re-resolve DNS at request time.
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)
        }
    except OSError as exc:
        return (False, f"Base URL 主机名无法解析 (DNS): {host}: {exc}")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        try:
            _check_ip_address(ip, allow_private)
        except ValueError as exc:
            return (False, str(exc))

    return (True, "OK")


# --------------------------------------------------------------------------
# Encryption-key rotation
# --------------------------------------------------------------------------

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
